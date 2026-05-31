"""One-shot scheduled 长鑫/CXMT deep-dive run.

Creates both:
  - research_reports(kind='deep_dive') via the main research deep-dive prompt
  - research_reports(kind='deep_qa') via the progressive Q&A drill-down

Then pushes to Render when configured and sends a completion email.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from stock import emailer, qa_deepdive
from stock.cloud_sync import run_local_sync
from stock.db import get_conn
from stock.research import generate_deep_dive


TOPIC = (
    "长鑫存储 / CXMT full cycle deep dive: DRAM/HBM shortage, China memory "
    "replacement, wafer-price inflation, capacity expansion cycle, historical "
    "memory boom-bust timing, related public beneficiaries, and 2027 peak/sell timing"
)

EXTRA_CONTEXT = """
Boss request:
- 好好推理一下. The operator may allocate 100-150万 and hold until around 2027-06.
- Need to sell slightly after the peak, not after the crash.
- Deeply mine historical crash/revival nodes, hot-cycle duration, expansion-cycle timing,
  shortage end timing, and likely peak timing for this cycle.
- Output must be concise, logically layered, non-overlapping, and easy to extract.
- Include 长鑫/CXMT logic plus public-market read-throughs: US, China, Taiwan, Japan if relevant.
- Use silicon wafer price-hike context: 信越化学, SUMCO, 环球晶, 688783.SH 西安奕材,
  688126.SS 沪硅产业, wafer shortage, AI demand reaching base materials.
- Explicitly distinguish:
  1. what is certain,
  2. what is probabilistic,
  3. what would invalidate the thesis,
  4. what data to watch monthly/quarterly,
  5. when to scale in, hold, trim, or exit.
- Include a cycle table with approximate timing: previous memory upcycles, peak, capex response,
  oversupply/crash, and recovery.
- This is research support, not financial advice.
"""

QA_SEED = (
    "Is 长鑫/CXMT and the China memory replacement cycle a major 2026-2027 opportunity, "
    "and when would shortage/peak/oversupply likely arrive?"
)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    conn = get_conn()
    try:
        deep = generate_deep_dive(
            conn,
            topic=TOPIC,
            extra_context=EXTRA_CONTEXT,
            language="zh-en",
            max_chars=14000,
        )
        qa = qa_deepdive.run_and_persist(
            ticker="CXMT/长鑫存储",
            seed_thesis=QA_SEED,
            conn=conn,
            rounds=5,
        )
        sync = run_local_sync(conn)
        body = (
            f"Scheduled 长鑫/CXMT deep dive completed at "
            f"{datetime.now(timezone.utc).isoformat()} UTC.\n\n"
            f"- deep_dive research_id: {deep.research_id}\n"
            f"- deep_qa research_id: {qa.research_id}\n"
            f"- Render sync: notes={sync.notes_pushed}, tokens={sync.tokens_pushed}, "
            f"replies={sync.replies_pulled}, error={sync.error or 'none'}\n\n"
            "Open the Boss app / dashboard notes list to read and download/share."
        )
        emailer.send_email(subject="STOCK 长鑫/CXMT scheduled deep dive complete", body=body)
        print(body)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
