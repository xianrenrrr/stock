"""tests.test_bandit -- Thompson sampling bandit tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stock.bandit import (
    ArmConfig,
    BanditSelection,
    _ensure_arm_state,
    get_ticker_bucket,
    select_arm,
    update_arm_posterior,
)


def _insert_arm_state(
    conn: sqlite3.Connection,
    arm: str,
    bucket: str,
    alpha: float = 1.0,
    beta: float = 1.0,
    pulls: int = 0,
) -> None:
    """Insert a bandit_state row with given posteriors."""
    conn.execute(
        "INSERT OR REPLACE INTO bandit_state"
        " (strategy_arm, ticker_bucket, alpha, beta, pulls, reward_sum, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 0.0, ?)",
        (arm, bucket, alpha, beta, pulls, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


TWO_ARMS: list[ArmConfig] = [
    ArmConfig(name="arm_a", provider="minimax", model="model-a"),
    ArmConfig(name="arm_b", provider="minimax", model="model-b"),
]


def test_get_ticker_bucket() -> None:
    """Ticker bucket is the ticker itself."""
    assert get_ticker_bucket("AAPL") == "AAPL"
    assert get_ticker_bucket("MSFT") == "MSFT"


def test_select_arm_single_arm(mem_db: sqlite3.Connection) -> None:
    """With one registered arm, always returns that arm."""
    result = select_arm("AAPL", mem_db)

    assert isinstance(result, BanditSelection)
    assert result.strategy_arm == "codex_cli/default"
    assert result.provider == "codex_cli"
    assert result.model == "codex-cli-session"


def test_select_arm_creates_state_row(mem_db: sqlite3.Connection) -> None:
    """select_arm creates a bandit_state row if none exists."""
    select_arm("AAPL", mem_db)

    row = mem_db.execute(
        "SELECT alpha, beta, pulls FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("codex_cli/default", "AAPL"),
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(1.0)
    assert row[1] == pytest.approx(1.0)
    assert row[2] == 0


@patch("stock.bandit.REGISTERED_ARMS", TWO_ARMS)
def test_select_arm_multiple_arms_returns_valid(mem_db: sqlite3.Connection) -> None:
    """With 2 arms, returns one of them."""
    result = select_arm("AAPL", mem_db)

    assert result.strategy_arm in ("arm_a", "arm_b")
    assert result.provider == "minimax"


@patch("stock.bandit.REGISTERED_ARMS", TWO_ARMS)
def test_thompson_sampling_shifts_selection(mem_db: sqlite3.Connection) -> None:
    """Strong posterior for arm_a causes it to be selected >90% of the time."""
    # Set arm_a to strong winner, arm_b to strong loser
    _insert_arm_state(mem_db, "arm_a", "AAPL", alpha=21.0, beta=1.0, pulls=20)
    _insert_arm_state(mem_db, "arm_b", "AAPL", alpha=1.0, beta=21.0, pulls=20)

    # Run 100 selections and count
    counts: dict[str, int] = {"arm_a": 0, "arm_b": 0}
    for _ in range(100):
        result = select_arm("AAPL", mem_db)
        counts[result.strategy_arm] += 1

    assert counts["arm_a"] > 90


def test_update_arm_posterior_reward(mem_db: sqlite3.Connection) -> None:
    """Reward=1.0 increments alpha by 1, beta unchanged."""
    _insert_arm_state(mem_db, "minimax/default", "AAPL", alpha=1.0, beta=1.0)

    update_arm_posterior("minimax/default", "AAPL", 1.0, mem_db)
    mem_db.commit()

    row = mem_db.execute(
        "SELECT alpha, beta, pulls, reward_sum FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert row[0] == pytest.approx(2.0)
    assert row[1] == pytest.approx(1.0)
    assert row[2] == 1
    assert row[3] == pytest.approx(1.0)


def test_update_arm_posterior_no_reward(mem_db: sqlite3.Connection) -> None:
    """Reward=0.0 increments beta by 1, alpha unchanged."""
    _insert_arm_state(mem_db, "minimax/default", "AAPL", alpha=1.0, beta=1.0)

    update_arm_posterior("minimax/default", "AAPL", 0.0, mem_db)
    mem_db.commit()

    row = mem_db.execute(
        "SELECT alpha, beta, pulls, reward_sum FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert row[0] == pytest.approx(1.0)
    assert row[1] == pytest.approx(2.0)
    assert row[2] == 1
    assert row[3] == pytest.approx(0.0)


def test_ensure_arm_state_idempotent(mem_db: sqlite3.Connection) -> None:
    """Calling _ensure_arm_state twice does not duplicate or change posteriors."""
    _ensure_arm_state("minimax/default", "AAPL", mem_db)
    _ensure_arm_state("minimax/default", "AAPL", mem_db)

    rows = mem_db.execute(
        "SELECT COUNT(*) FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert rows[0] == 1

    row = mem_db.execute(
        "SELECT alpha, beta FROM bandit_state"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        ("minimax/default", "AAPL"),
    ).fetchone()
    assert row[0] == pytest.approx(1.0)
    assert row[1] == pytest.approx(1.0)
