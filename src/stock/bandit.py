"""stock.bandit -- Thompson sampling over prediction strategy arms."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_ALPHA: float = 1.0
DEFAULT_BETA: float = 1.0


class ArmConfig(BaseModel):
    """Configuration for a single bandit arm."""

    name: str
    provider: str
    model: str


class BanditSelection(BaseModel):
    """Result of arm selection for a prediction cycle."""

    strategy_arm: str
    provider: str
    model: str


REGISTERED_ARMS: list[ArmConfig] = [
    ArmConfig(name="minimax/default", provider="minimax", model="MiniMax-M1-80k"),
]


def get_ticker_bucket(ticker: str) -> str:
    """Map a ticker to its bandit bucket (1:1 for now)."""
    return ticker


def _ensure_arm_state(
    strategy_arm: str, ticker_bucket: str, conn: sqlite3.Connection
) -> None:
    """Insert a uniform-prior row into bandit_state if none exists."""
    conn.execute(
        "INSERT OR IGNORE INTO bandit_state"
        " (strategy_arm, ticker_bucket, alpha, beta, pulls, reward_sum, updated_at)"
        " VALUES (?, ?, ?, ?, 0, 0.0, ?)",
        (strategy_arm, ticker_bucket, DEFAULT_ALPHA, DEFAULT_BETA,
         datetime.now(timezone.utc).isoformat()),
    )


def select_arm(ticker: str, conn: sqlite3.Connection) -> BanditSelection:
    """Pick a strategy arm via Thompson sampling."""
    if not REGISTERED_ARMS:
        raise RuntimeError("No strategy arms registered")

    bucket = get_ticker_bucket(ticker)

    # Single arm fast path -- no sampling needed
    if len(REGISTERED_ARMS) == 1:
        arm = REGISTERED_ARMS[0]
        _ensure_arm_state(arm.name, bucket, conn)
        return BanditSelection(
            strategy_arm=arm.name, provider=arm.provider, model=arm.model
        )

    # Ensure state rows exist for every arm
    for arm in REGISTERED_ARMS:
        _ensure_arm_state(arm.name, bucket, conn)

    # Sample from Beta posterior for each arm and pick the highest
    rng = np.random.default_rng()
    best_arm = REGISTERED_ARMS[0]
    best_sample = -1.0

    for arm in REGISTERED_ARMS:
        row = conn.execute(
            "SELECT alpha, beta FROM bandit_state"
            " WHERE strategy_arm = ? AND ticker_bucket = ?",
            (arm.name, bucket),
        ).fetchone()
        alpha = float(row[0])
        beta = float(row[1])
        sample = float(rng.beta(alpha, beta))
        if sample > best_sample:
            best_sample = sample
            best_arm = arm

    return BanditSelection(
        strategy_arm=best_arm.name, provider=best_arm.provider, model=best_arm.model
    )


def update_arm_posterior(
    strategy_arm: str,
    ticker_bucket: str,
    reward: float,
    conn: sqlite3.Connection,
) -> None:
    """Update Beta posteriors for an arm after observing a reward."""
    conn.execute(
        "UPDATE bandit_state"
        " SET alpha = alpha + ?, beta = beta + (1.0 - ?), pulls = pulls + 1,"
        "     reward_sum = reward_sum + ?, updated_at = ?"
        " WHERE strategy_arm = ? AND ticker_bucket = ?",
        (reward, reward, reward, datetime.now(timezone.utc).isoformat(),
         strategy_arm, ticker_bucket),
    )
