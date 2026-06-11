"""tests.conftest -- shared pytest fixtures."""
from __future__ import annotations

import sqlite3
from typing import Generator

import pytest

from stock.config import Settings, get_settings
from stock.db import get_conn


@pytest.fixture()
def mem_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield an in-memory SQLite connection with schema created."""
    conn = get_conn(":memory:")
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _no_network_market_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests hermetic: H0 market-context live lookups never hit yfinance."""
    monkeypatch.setattr(
        "stock.market_context.fetch_live_quote", lambda _t: None, raising=True,
    )
    monkeypatch.setattr(
        "stock.market_context.fetch_next_earnings_date", lambda _t: None, raising=True,
    )


@pytest.fixture()
def env_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[Settings, None, None]:
    """Return a Settings instance with test env vars, clearing lru_cache."""
    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("MINIMAX_API_KEY", "test")
    monkeypatch.setenv("STOCK_API_TOKEN", "test")
    monkeypatch.setenv("DAILY_COST_CEILING_USD", "1.00")
    monkeypatch.setenv("DB_PATH", ":memory:")
    settings = Settings()
    yield settings
    get_settings.cache_clear()
