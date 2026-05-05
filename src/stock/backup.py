"""stock.backup -- nightly SQLite backup so we don't lose state to corruption.

Cheap insurance: SQLite supports an online backup API that takes a consistent
snapshot WITHOUT pausing writes. We copy the live DB to data/backups/stock.db.<date>
once a day, retain the last N copies, and prune older ones.

Hooked into the orchestrator at 23:30 UTC daily (between discovery_engine
at 23:00 and the morning research push at 02:30).
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from stock.config import get_settings

logger = logging.getLogger(__name__)

BACKUP_DIR: str = "data/backups"
RETAIN_COUNT: int = 7  # keep the last week's daily backups


class BackupResult(BaseModel):
    """Outcome of one backup_now run."""

    backup_path: str
    bytes: int
    pruned_count: int


def _backup_filename(now: datetime) -> str:
    """Stable filename so re-running on the same day overwrites instead of duplicates."""
    return f"stock.db.{now.strftime('%Y-%m-%d')}.bak"


def backup_now(*, now: datetime | None = None) -> BackupResult:
    """Take an online SQLite backup of the live DB and prune older copies.

    Uses sqlite3's `.backup()` API which is safe to run while the DB is being
    written to. Falls back to shutil.copy2 if the source is :memory: or
    missing (tests).
    """
    settings = get_settings()
    src_path = Path(settings.db_path)
    if not src_path.exists() or settings.db_path == ":memory:":
        raise FileNotFoundError(f"Source DB not found / is in-memory: {settings.db_path}")

    backup_dir = Path(BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    moment = now or datetime.now(timezone.utc)
    dst = backup_dir / _backup_filename(moment)

    # Online backup via sqlite3's backup API (safe under concurrent writes)
    src_conn = sqlite3.connect(str(src_path))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    bytes_written = dst.stat().st_size
    pruned = _prune_old_backups(backup_dir)
    logger.info(
        "DB backup written: %s (%.1f MB), pruned %d older copies",
        dst.name, bytes_written / (1024 * 1024), pruned,
    )
    return BackupResult(
        backup_path=str(dst), bytes=bytes_written, pruned_count=pruned,
    )


def _prune_old_backups(backup_dir: Path) -> int:
    """Keep only the RETAIN_COUNT most recent .bak files; delete the rest."""
    files = sorted(
        [p for p in backup_dir.glob("stock.db.*.bak")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    pruned = 0
    for old in files[RETAIN_COUNT:]:
        try:
            old.unlink()
            pruned += 1
        except OSError:
            logger.warning("Could not prune old backup %s", old, exc_info=True)
    return pruned


def list_backups() -> list[tuple[str, int]]:
    """Return [(filename, bytes), ...] for backups in data/backups/, newest first."""
    backup_dir = Path(BACKUP_DIR)
    if not backup_dir.exists():
        return []
    files = sorted(
        [p for p in backup_dir.glob("stock.db.*.bak")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [(p.name, p.stat().st_size) for p in files]
