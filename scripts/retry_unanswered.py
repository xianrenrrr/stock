"""scripts.retry_unanswered -- one-off backfill of replies for boss messages stuck without answers."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

# Ensure stdout handles Chinese
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from stock import conversation
from stock.db import get_conn
from stock.research import generate_reply

SKIP_PHRASES = ("test from curl",)


def _select_unanswered(conn: sqlite3.Connection) -> list[tuple[int, str, str, str]]:
    """Return one inbound row per unique body (no matching outbound yet)."""
    rows = conn.execute(
        """
        SELECT c.id, c.run_id, c.recipient, c.body, c.created_at
        FROM conversations c
        WHERE c.direction='inbound'
        AND NOT EXISTS (
            SELECT 1 FROM conversations o
            WHERE o.direction='outbound' AND o.run_id=c.run_id
        )
        ORDER BY c.created_at ASC
        """
    ).fetchall()

    # Dedupe by body, keep newest row (so we use the F13-created one with full timestamp)
    by_body: dict[str, tuple[int, str, str, str]] = {}
    for cid, run_id, recipient, body, created_at in rows:
        body = str(body)
        if any(skip in body.lower() for skip in SKIP_PHRASES):
            continue
        # Always keep the LATER row (later timestamp wins)
        prev = by_body.get(body)
        if prev is None or created_at > prev[3]:
            by_body[body] = (int(cid), str(run_id), str(recipient), str(created_at))
    return [(cid, run_id, recipient, body, created_at)
            for body, (cid, run_id, recipient, created_at) in by_body.items()]


def main() -> None:
    """Iterate stuck messages and generate one reply per unique body."""
    conn = get_conn()
    targets = _select_unanswered(conn)
    print(f"Found {len(targets)} stuck unique boss messages to answer.")
    print()

    succeeded = 0
    failed = 0
    for idx, (cid, run_id, recipient, body, created_at) in enumerate(targets, start=1):
        body_short = body.replace("\n", " ")[:120]
        print(f"[{idx}/{len(targets)}] inbound id={cid} ({created_at[:16]}): {body_short}")
        try:
            reply_body = generate_reply(conn, recipient=recipient, boss_reply=body)
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            failed += 1
            continue

        topic_short = body.strip().replace("\n", " ")[:120]
        cursor = conn.execute(
            "INSERT INTO research_reports"
            " (kind, topic, layer_focus, body, cost_usd, created_at)"
            " VALUES ('reply', ?, NULL, ?, 0, ?)",
            (topic_short, reply_body, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        reply_research_id = int(cursor.lastrowid or 0) or None
        conversation.record_outbound(
            recipient, reply_body, conn,
            run_id=run_id, related_research_id=reply_research_id,
        )
        print(f"  OK reply_research_id={reply_research_id} reply_len={len(reply_body)}")
        succeeded += 1

    print()
    print(f"Done: succeeded={succeeded} failed={failed}")
    conn.close()


if __name__ == "__main__":
    main()
