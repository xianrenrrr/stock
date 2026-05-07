"""scripts/run_dive_queue.py -- process all enabled topics in data/topic_queue.yaml.

Usage: python scripts/run_dive_queue.py [--limit N]

Sequential execution -- each tech-dive uses claude_cli (subprocess to local
Claude session) so they have to run one-at-a-time anyway. Updates last_run
in topic_queue.yaml after each completion. Dive output persists to the
research_reports table; this script just orchestrates the loop.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stock.db import get_conn
from stock.tech_dive import run_and_persist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Stop after N dives")
    parser.add_argument("--queue", default="data/topic_queue.yaml")
    args = parser.parse_args()

    queue_path = Path(args.queue)
    data = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or {}
    topics = data.get("topics") or []

    enabled = [t for t in topics if t.get("enabled", True)]
    if args.limit:
        enabled = enabled[:args.limit]

    print(f"Processing {len(enabled)} enabled topics from {queue_path}")
    conn = get_conn()
    completed = 0
    for i, t in enumerate(enabled, start=1):
        sector = str(t.get("sector", "information"))
        topic = str(t.get("topic", ""))
        if not topic:
            continue
        print(f"\n=== [{i}/{len(enabled)}] {sector} ===")
        print(f"Topic: {topic[:100]}")
        start = datetime.now(timezone.utc)
        try:
            dive = run_and_persist(
                topic=topic, sector=sector, conn=conn, language="zh-en",
            )
        except Exception as exc:  # noqa: BLE001 -- per-topic isolation
            print(f"  FAILED: {exc}")
            continue
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        if dive.rounds:
            print(f"  -> {len(dive.rounds)} rounds, research_id={dive.research_id}, "
                  f"{elapsed:.0f}s")
            t["last_run"] = start.strftime("%Y-%m-%d")
            completed += 1
        else:
            print(f"  -> 0 rounds (likely cost ceiling or backend down); not persisted")

    # Persist last_run updates
    queue_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=200),
        encoding="utf-8",
    )
    print(f"\nDone: {completed}/{len(enabled)} dives completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
