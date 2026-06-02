"""tests.test_backup -- F33 nightly SQLite online backup."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock import backup


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a real on-disk SQLite DB and point Settings at it."""
    db_path = tmp_path / "stock.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE foo (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO foo VALUES (1, 'hello')")
    conn.commit()
    conn.close()

    fake_settings = MagicMock()
    fake_settings.db_path = str(db_path)
    monkeypatch.setattr("stock.backup.get_settings", lambda: fake_settings)
    monkeypatch.setattr("stock.backup.BACKUP_DIR", str(tmp_path / "backups"))
    return db_path


def test_backup_now_writes_dst(tmp_db: Path, tmp_path: Path) -> None:
    """backup_now copies the live DB to data/backups/ with dated filename."""
    result = backup.backup_now()
    assert Path(result.backup_path).exists()
    assert result.bytes > 0
    # Backup should be readable as a valid SQLite db
    conn = sqlite3.connect(result.backup_path)
    rows = conn.execute("SELECT name FROM foo WHERE id = 1").fetchall()
    conn.close()
    assert rows == [("hello",)]


def test_backup_idempotent_on_same_day(tmp_db: Path) -> None:
    """Re-running backup on the same day overwrites instead of duplicating."""
    backup.backup_now()
    list_before = backup.list_backups()
    backup.backup_now()
    list_after = backup.list_backups()
    assert len(list_after) == len(list_before)


def test_backup_prunes_old_files(tmp_db: Path, tmp_path: Path) -> None:
    """Older-than-RETAIN_COUNT backups get deleted."""
    # Create 10 fake old backups manually
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    base = datetime.now(timezone.utc)
    for i in range(10):
        old = backup_dir / f"stock.db.{(base - timedelta(days=i + 1)).strftime('%Y-%m-%d')}.bak"
        old.write_bytes(b"fake")
        # Backdate the mtime so the prune sort knows their age
        ts = (base - timedelta(days=i + 1)).timestamp()
        import os
        os.utime(old, (ts, ts))

    result = backup.backup_now()
    files = backup.list_backups()
    # Should retain RETAIN_COUNT + the new one we just created (could be merged
    # if today's date matched, but most likely 7 retained)
    assert len(files) <= backup.RETAIN_COUNT
    assert result.pruned_count > 0


def test_backup_missing_source_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source DB missing -> FileNotFoundError (orchestrator catches it)."""
    fake = MagicMock()
    fake.db_path = "/nonexistent/path.db"
    monkeypatch.setattr("stock.backup.get_settings", lambda: fake)
    with pytest.raises(FileNotFoundError):
        backup.backup_now()
