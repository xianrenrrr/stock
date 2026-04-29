"""tests.test_ingest_prices -- price ingestion tests with mocked yfinance."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from stock.ingest import PriceBar, fetch_prices
from stock.ingest.prices import fetch_daily_prices

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def prices_dataframe_fixture() -> pd.DataFrame:
    """DataFrame mimicking yfinance.download output."""
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    data = {
        "Open": [150.0, 151.0, 152.0, 153.0, 154.0],
        "High": [155.0, 156.0, 157.0, 158.0, 159.0],
        "Low": [149.0, 150.0, 151.0, 152.0, 153.0],
        "Close": [154.0, 155.0, 156.0, 157.0, 158.0],
        "Volume": [1000000, 1100000, 1200000, 1300000, 1400000],
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture()
def prices_dataframe_with_nan(prices_dataframe_fixture: pd.DataFrame) -> pd.DataFrame:
    """DataFrame with some NaN rows."""
    df = prices_dataframe_fixture.copy()
    df.loc[df.index[2], "Close"] = np.nan
    return df


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@patch("stock.ingest.prices.yfinance.download")
def test_fetch_daily_prices_returns_bars(
    mock_download: object, prices_dataframe_fixture: pd.DataFrame
) -> None:
    mock_download.return_value = prices_dataframe_fixture  # type: ignore[union-attr]
    bars = fetch_daily_prices("AAPL", days=30)
    assert len(bars) == 5
    assert all(isinstance(b, PriceBar) for b in bars)
    assert bars[0].ticker == "AAPL"
    assert bars[0].o == 150.0
    assert bars[0].c == 154.0


@patch("stock.ingest.prices.yfinance.download")
def test_fetch_daily_prices_empty_dataframe(mock_download: object) -> None:
    mock_download.return_value = pd.DataFrame()  # type: ignore[union-attr]
    bars = fetch_daily_prices("UNKNOWN", days=30)
    assert bars == []


@patch("stock.ingest.prices.yfinance.download")
def test_fetch_daily_prices_drops_nan_rows(
    mock_download: object, prices_dataframe_with_nan: pd.DataFrame
) -> None:
    mock_download.return_value = prices_dataframe_with_nan  # type: ignore[union-attr]
    bars = fetch_daily_prices("AAPL", days=30)
    assert len(bars) == 4


# ---------------------------------------------------------------------------
# Integration tests (fetch_prices orchestrator)
# ---------------------------------------------------------------------------

@patch("stock.ingest.prices.yfinance.download")
def test_prices_written_to_db(
    mock_download: object,
    mem_db: sqlite3.Connection,
    prices_dataframe_fixture: pd.DataFrame,
) -> None:
    mock_download.return_value = prices_dataframe_fixture  # type: ignore[union-attr]
    result = fetch_prices("AAPL", mem_db, days=30)
    assert result.inserted == 5
    rows = mem_db.execute("SELECT COUNT(*) FROM prices WHERE ticker = 'AAPL'").fetchone()
    assert rows[0] == 5


@patch("stock.ingest.prices.yfinance.download")
def test_prices_dedup_composite_pk(
    mock_download: object,
    mem_db: sqlite3.Connection,
    prices_dataframe_fixture: pd.DataFrame,
) -> None:
    mock_download.return_value = prices_dataframe_fixture  # type: ignore[union-attr]

    # First insert
    fetch_prices("AAPL", mem_db, days=30)
    # Second insert with same data
    result = fetch_prices("AAPL", mem_db, days=30)

    assert result.skipped == 5
    assert result.inserted == 0
    rows = mem_db.execute("SELECT COUNT(*) FROM prices WHERE ticker = 'AAPL'").fetchone()
    assert rows[0] == 5


@patch("stock.ingest.prices.yfinance.download")
def test_prices_dry_run_does_not_write(
    mock_download: object,
    mem_db: sqlite3.Connection,
    prices_dataframe_fixture: pd.DataFrame,
) -> None:
    mock_download.return_value = prices_dataframe_fixture  # type: ignore[union-attr]
    result = fetch_prices("AAPL", mem_db, days=30, dry_run=True)
    assert result.inserted == 0
    rows = mem_db.execute("SELECT COUNT(*) FROM prices").fetchone()
    assert rows[0] == 0
