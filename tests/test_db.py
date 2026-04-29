"""tests.test_db -- verify schema creation on :memory: SQLite."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from stock.db import _ensure_schema, get_conn

EXPECTED_TABLES = {
    "news",
    "prices",
    "features",
    "predictions",
    "outcomes",
    "rules",
    "bandit_state",
    "calibration",
    "watchlist",
    "llm_calls",
    "case_embeddings",
}


class TestSchema:
    def test_schema_creates_all_tables(self, mem_db: sqlite3.Connection) -> None:
        """All expected tables are created in a fresh :memory: database."""
        cursor = mem_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert EXPECTED_TABLES.issubset(tables)

    def test_schema_idempotent(self, mem_db: sqlite3.Connection) -> None:
        """Running _ensure_schema twice does not raise errors."""
        _ensure_schema(mem_db)
        _ensure_schema(mem_db)

    def test_foreign_keys_enabled(self, mem_db: sqlite3.Connection) -> None:
        """Foreign keys pragma is turned on."""
        result = mem_db.execute("PRAGMA foreign_keys").fetchone()
        assert result is not None
        assert result[0] == 1

    def test_wal_mode_on_file_db(self) -> None:
        """WAL journal mode is set for file-based databases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            conn = get_conn(db_path)
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result is not None
            assert result[0] == "wal"
            conn.close()

    def test_insert_and_read_news(self, mem_db: sqlite3.Connection) -> None:
        """A row inserted into news can be read back."""
        mem_db.execute(
            "INSERT INTO news (ticker, source, url, title, body, ts, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "yahoo", "https://example.com/1", "Apple up", "body",
             "2025-01-01T00:00:00Z", "2025-01-01T00:01:00Z"),
        )
        mem_db.commit()
        row = mem_db.execute("SELECT ticker, title FROM news WHERE id = 1").fetchone()
        assert row is not None
        assert row[0] == "AAPL"
        assert row[1] == "Apple up"

    def test_case_embeddings_table_exists(self, mem_db: sqlite3.Connection) -> None:
        """case_embeddings vec0 virtual table is created by schema."""
        row = mem_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='case_embeddings'"
        ).fetchone()
        assert row is not None

    def test_prices_composite_pk(self, mem_db: sqlite3.Connection) -> None:
        """Duplicate (ticker, ts) insert raises IntegrityError."""
        mem_db.execute(
            "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", 150.0, 155.0, 149.0, 153.0, 1000000),
        )
        mem_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            mem_db.execute(
                "INSERT INTO prices (ticker, ts, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-01-01", 151.0, 156.0, 150.0, 154.0, 2000000),
            )
