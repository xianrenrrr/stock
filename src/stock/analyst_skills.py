"""stock.analyst_skills -- equity-research-style skills adapted from
anthropics/financial-services to STOCK's forward-looking workflow.

Three skills, all routed through get_core_client() (free via claude_cli):

  earnings_review(ticker, conn) -- post-earnings 3-round structured analysis
  dd_checklist(ticker, conn)    -- 8-item due-diligence punch list (1 round)
  morning_note(conn)            -- tight overnight roll-up across conviction names

Persisted as research_reports rows with new kinds:
  earnings_review | dd_checklist | morning_note

These integrate with the existing pipeline: APK auto-syncs all research_reports,
daily-zh report counts them by kind, the cloud_sync 5s cron pushes to Render.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import CostCeilingError, check_cost_ceiling
from stock.research import _core_chat
from stock.tech_trends import load_conviction

logger = logging.getLogger(__name__)

EARNINGS_ROUND_MAX_TOKENS: int = 1500
DD_CHECKLIST_MAX_TOKENS: int = 2000
MORNING_NOTE_MAX_TOKENS: int = 1800


class SkillReport(BaseModel):
    """Generic report wrapper for the 3 skills."""

    ticker: str | None
    kind: str  # earnings_review | dd_checklist | morning_note
    body: str
    research_id: int | None = None
    created_at: str


# ============================================================================
# Earnings review -- 3-round structured (per-ticker, post-print)
# ============================================================================


_EARNINGS_ROUND_PROMPTS: list[tuple[str, str]] = [
    (
        "results_vs_expectations",
        "## Round 1 / 第一轮 -- 业绩 vs 预期 / Beat-miss vs expectations\n\n"
        "For {ticker} (use real numbers from the most recent earnings print -- "
        "search if not in your context). In {language}:\n"
        "1. **Headline numbers**: revenue, EPS (GAAP and non-GAAP), guidance.\n"
        "2. **Beat/miss vs consensus** -- quantify (specific dollar/percent).\n"
        "3. **Segment / geographic mix** -- which line drove the surprise?\n"
        "4. **Margin trends** -- gross, operating, net QoQ + YoY.\n"
        "5. **Forward guidance change** -- raised / maintained / lowered, by how much.\n"
        "Keep it tight; cite specific numbers.\n"
        "If you don't have the latest print, say so explicitly -- don't invent."
    ),
    (
        "thesis_impact",
        "## Round 2 / 第二轮 -- 论点冲击 / Thesis impact\n\n"
        "Build on Round 1. In {language}:\n"
        "1. **What changed in the FORWARD investment thesis** -- not the backward "
        "narrative. Specifically: was the structural driver (e.g. AI-DC ramp, "
        "GLP-1 demand, gene-editing scale) confirmed, accelerated, or weakened?\n"
        "2. **What the Q&A on the earnings call revealed** -- the most important "
        "single management answer (or non-answer); the most pointed analyst question.\n"
        "3. **Cross-read for OTHER tickers** -- name 2-3 names whose thesis "
        "implicates from this print (e.g. NVDA print -> COHR/LITE/ACMR cross-reads).\n"
        "4. **Revised invalidation triggers** -- 2-3 specific observable signals "
        "that would now break the thesis."
    ),
    (
        "position_update",
        "## Round 3 / 第三轮 -- 仓位决策 / Position decision\n\n"
        "Synthesis. In {language}:\n"
        "- **Action**: ADD / HOLD / TRIM / EXIT, plus the specific scenario "
        "that would flip the action (e.g. 'TRIM if next-quarter guidance "
        "deceleration > 5pp').\n"
        "- **Stop-loss reset**: based on the new information, where should "
        "the auto-stop sit? Cite the F24 ATR-based level if known, or note "
        "that a cost-anchored stop is appropriate post-pop.\n"
        "- **Conviction confidence (1-10)** -- pre-print vs post-print, with "
        "one sentence on why the delta.\n"
        "- **One-line takeaway** for the boss.\n\n"
        "End with the literal disclaimer: 'Not financial advice.'"
    ),
]


def _build_skill_prompt(
    ticker: str | None, language: str, prior_rounds: list[str], instructions: str,
) -> str:
    """Assemble a prompt for one skill round, including prior transcript."""
    history = "\n\n".join(prior_rounds) or "(No prior rounds; this is round 1.)"
    ticker_line = f"**Ticker:** {ticker}" if ticker else ""
    return (
        f"{ticker_line}\n"
        f"**Output language:** {language}\n\n"
        f"**Research workflow:** Search and reason in **English** — English "
        f"sources (SEC, Bloomberg, FactSet, IR, sell-side) are far richer for "
        f"US equities. **Only translate the FINAL deliverable body into "
        f"{language}.** Keep tickers, company names, dates, numbers, and URLs "
        f"in canonical English/numeric form. Exception: A-share / HK names — "
        f"Chinese disclosures primary.\n\n"
        f"## Prior rounds in this analysis\n\n{history}\n\n"
        f"{instructions.format(ticker=ticker or 'the ticker', language=language)}"
    )


def earnings_review(
    *, ticker: str, conn: sqlite3.Connection, language: str = "zh",
) -> SkillReport:
    """Run the 3-round earnings review; persist as research_reports."""
    settings = get_settings()
    transcript: list[str] = []

    for i, (label, instructions) in enumerate(_EARNINGS_ROUND_PROMPTS, start=1):
        try:
            check_cost_ceiling(conn, settings)
            prompt = _build_skill_prompt(ticker, language, transcript, instructions)
            response = _core_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=EARNINGS_ROUND_MAX_TOKENS,
                conn=conn,
                caller=f"earnings_review_{ticker}_{label}",
            )
        except (CostCeilingError, Exception):
            logger.exception("earnings_review round %d failed for %s", i, ticker)
            break
        body = (response.content or "").strip()
        if not body:
            break
        transcript.append(f"### Round {i}: {label}\n\n{body}")

    full_body = (
        f"# {ticker} 业绩复盘 / Earnings review\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} | "
        f"{len(transcript)} rounds_\n\n---\n\n"
        + "\n\n---\n\n".join(transcript)
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if transcript:
        cur = conn.execute(
            "INSERT INTO research_reports (kind, topic, body, created_at)"
            " VALUES ('earnings_review', ?, ?, ?)",
            (f"{ticker} 业绩复盘", full_body, now),
        )
        conn.commit()
        rid = int(cur.lastrowid)
    else:
        rid = None
    return SkillReport(
        ticker=ticker.upper(), kind="earnings_review",
        body=full_body, research_id=rid, created_at=now,
    )


# ============================================================================
# DD checklist -- single-shot 8-item punch list
# ============================================================================


_DD_CHECKLIST_PROMPT: str = (
    "## 尽调清单 / Due-diligence checklist for {ticker}\n\n"
    "**Research workflow:** Search and reason in **English** — English sources "
    "(SEC filings, Bloomberg, FactSet, company IR, sell-side) are far richer "
    "for US/global equities. **Only translate the FINAL checklist body into "
    "{language}.** Keep tickers, company names, dates, numbers, currency, and "
    "URLs in canonical English/numeric form. Exception: {ticker} is an "
    "A-share / HK Chinese name — Chinese disclosures (Eastmoney, 巨潮资讯) "
    "are primary source.\n\n"
    "Produce a 12-item checklist for {ticker}, organized for a forward-looking "
    "long thesis. In {language}:\n\n"
    "Cover EXACTLY these categories, with concrete numbers / dates / sources "
    "where possible (cite '我不知道' when you don't have data, don't invent):\n\n"
    "1. **Business model + revenue mix** -- top 3 segments by % of revenue\n"
    "2. **Customer concentration** -- top customer + top 3 % of revenue\n"
    "3. **Competitive position** -- main 2 public competitors, market share if known\n"
    "4. **Margin trajectory** -- gross + operating margin trend last 4Q\n"
    "5. **Cash position + burn rate** -- cash, FCF latest Q, runway implications\n"
    "6. **Insider activity** -- recent Form 4 buys/sells if material\n"
    "7. **Capital allocation** -- buyback / dividend / acquisitions in last 12mo\n"
    "8. **Regulatory / litigation risk** -- specific named exposures\n"
    "9. **Catalyst calendar (next 90 days)** -- earnings date + named catalysts\n"
    "10. **Falsification triggers** -- 3 specific observable signals that would "
    "break a long thesis (numbers, dates, events)\n"
    "11. **Cleanest comparable (1 ticker)** + why\n"
    "12. **Bottom line**: one sentence -- in or out of conviction list, why\n\n"
    "Format: numbered list with 1-3 bullets each. Total ~600-1000 words.\n"
    "End with: 'Not financial advice.'"
)


def dd_checklist(
    *, ticker: str, conn: sqlite3.Connection, language: str = "zh",
) -> SkillReport:
    """Run a single-shot DD checklist; persist as research_reports."""
    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
        prompt = _DD_CHECKLIST_PROMPT.format(ticker=ticker, language=language)
        response = _core_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=DD_CHECKLIST_MAX_TOKENS,
            conn=conn,
            caller=f"dd_checklist_{ticker}",
        )
    except (CostCeilingError, Exception):
        logger.exception("dd_checklist failed for %s", ticker)
        return SkillReport(
            ticker=ticker.upper(), kind="dd_checklist", body="",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    full_body = (
        f"# {ticker} 尽调清单 / DD checklist\n\n"
        f"_Generated {now}_\n\n"
        f"{(response.content or '').strip()}"
    )
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('dd_checklist', ?, ?, ?)",
        (f"{ticker} 尽调清单", full_body, now),
    )
    conn.commit()

    # Boss directive 2026-05-08: don't keep creating new DD files; APPEND
    # each fresh run to a single per-company file at pipeline/dd/<TICKER>.md
    # so you can read the full DD history for one ticker in one place.
    # Skip the file-write when running on an in-memory test DB so unit tests
    # don't pollute the real pipeline/dd/ directory with fixture content.
    is_memory_db = False
    try:
        for row in conn.execute("PRAGMA database_list").fetchall():
            if row[2] == "" or ":memory:" in str(row[2]):
                is_memory_db = True
                break
    except sqlite3.Error:
        pass
    if is_memory_db:
        return SkillReport(
            ticker=ticker.upper(), kind="dd_checklist", body=full_body,
            research_id=int(cur.lastrowid), created_at=now,
        )

    from pathlib import Path
    safe = ticker.upper().replace("/", "_").replace("\\", "_").replace(".", "_")
    dd_path = Path("pipeline") / "dd" / f"{safe}.md"
    dd_path.parent.mkdir(parents=True, exist_ok=True)
    section = (
        f"\n\n---\n\n## DD run {now[:16]}  (research_id={cur.lastrowid})\n\n"
        f"{(response.content or '').strip()}\n"
    )
    if dd_path.exists():
        dd_path.write_text(
            dd_path.read_text(encoding="utf-8") + section, encoding="utf-8",
        )
    else:
        dd_path.write_text(
            f"# {ticker.upper()} -- 尽调历史 / DD history\n\n"
            f"_Cumulative DD checklist runs for this ticker. Each section is "
            f"one F44 cron fire. Newest at the bottom._\n"
            + section,
            encoding="utf-8",
        )

    return SkillReport(
        ticker=ticker.upper(), kind="dd_checklist", body=full_body,
        research_id=int(cur.lastrowid), created_at=now,
    )


# ============================================================================
# Morning note -- tight overnight roll-up across conviction names
# ============================================================================


def _build_morning_context(conn: sqlite3.Connection) -> str:
    """Pull last-24h signals from existing tables for the morning prompt.

    Volume convention (boss directive 2026-05-09, Option C): the volume
    figures here are PREVIOUS-SESSION 4 PM ET FINAL volume only, never
    today's not-yet-settled intraday partial. yfinance daily bars settle
    after 4 PM ET; the post-close cron at 20:05 UTC writes the authoritative
    row. Morning notes that fire BEFORE the next session opens reference
    yesterday's 4 PM number, which is fully settled and apples-to-apples
    with the trailing-20-day average.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    pieces: list[str] = []

    conviction = load_conviction(enabled_only=True)
    pieces.append(
        "## Conviction watchlist (today's tracked names)\n"
        + ", ".join(n.ticker for n in conviction[:20])
    )

    # PREVIOUS-SESSION close volume vs 20-day average, per conviction ticker.
    # This is the AUTHORITATIVE volume signal -- yesterday's 4 PM ET final.
    # Don't cite intraday volume in the morning note -- it's noise + bug-prone.
    pieces.append("\n## 上一交易日收盘量 / Previous-session FINAL volume vs 20d avg (4 PM ET, settled)")
    pieces.append("_Use these numbers ONLY when discussing volume. Do NOT mention 'today's volume' -- the next session may not have opened yet, and intraday partial-bars have been a source of bugs._")
    for n in conviction[:15]:
        rows = conn.execute(
            "SELECT ts, c, v FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 21",
            (n.ticker,),
        ).fetchall()
        if len(rows) < 5:
            continue
        latest_ts, latest_c, latest_v = rows[0]
        prior_v = [r[2] for r in rows[1:21]]
        avg = sum(prior_v) / len(prior_v) if prior_v else 0
        ratio = latest_v / avg if avg else 0
        flag = " 🚨 SPIKE" if ratio >= 2.0 else (" 💤 quiet" if ratio <= 0.5 else "")
        pct = (latest_c / rows[1][1] - 1) * 100 if len(rows) > 1 and rows[1][1] else 0
        pieces.append(
            f"- {n.ticker} [{latest_ts[:10]}]: ${latest_c:.2f} ({pct:+.2f}%) "
            f"vol={int(latest_v):,} ({ratio:.2f}x avg){flag}"
        )

    rows = conn.execute(
        "SELECT ticker, ts, pct_change, volume_ratio, flag_reason FROM price_anomalies"
        " WHERE created_at >= ? ORDER BY ts DESC LIMIT 8",
        (yesterday,),
    ).fetchall()
    if rows:
        pieces.append("\n## Last-24h price/volume anomalies (F12)")
        for t, ts, pct, vol, reason in rows:
            pieces.append(f"- [{ts[:10]}] {t} pct={pct*100:+.2f}% vol={vol:.1f}x ({reason})")

    rows = conn.execute(
        "SELECT ticker, contract_symbol, option_type, strike, vol_oi_ratio, flag_reason"
        " FROM option_anomalies WHERE detected_at >= ?"
        " ORDER BY score DESC LIMIT 6",
        (yesterday,),
    ).fetchall()
    if rows:
        pieces.append("\n## Last-24h unusual options activity (F36)")
        for t, sym, otype, strike, ratio, reason in rows:
            pieces.append(f"- {t} {otype.upper()} ${strike:.0f} V/OI={ratio:.0f}x ({reason})")

    rows = conn.execute(
        "SELECT ticker, call_volume, put_volume, call_put_volume_ratio,"
        " put_call_volume_ratio FROM option_ratio_snapshots WHERE detected_at >= ?"
        " ORDER BY detected_at DESC, ticker ASC LIMIT 8",
        (yesterday,),
    ).fetchall()
    if rows:
        pieces.append("\n## Last-24h options call/put ratios")
        for t, call_vol, put_vol, cp_ratio, pc_ratio in rows:
            cp = f"{cp_ratio:.2f}x" if cp_ratio is not None else "-"
            pc = f"{pc_ratio:.2f}x" if pc_ratio is not None else "-"
            pieces.append(
                f"- {t}: C/P vol={cp}, P/C vol={pc} "
                f"(calls={call_vol:,}, puts={put_vol:,})"
            )

    rows = conn.execute(
        "SELECT topic, substr(body, 1, 100) FROM research_reports"
        " WHERE kind = 'alert' AND created_at >= ? ORDER BY created_at DESC LIMIT 3",
        (yesterday,),
    ).fetchall()
    if rows:
        pieces.append("\n## Last-24h holding alerts")
        for topic, excerpt in rows:
            pieces.append(f"- **{topic}**: {excerpt}...")

    rows = conn.execute(
        "SELECT title, ticker, ts FROM news"
        " WHERE ticker IN (" + ",".join("?" * len(conviction)) + ")"
        " AND ts >= ? ORDER BY ts DESC LIMIT 12",
        (*[n.ticker for n in conviction], yesterday),
    ).fetchall() if conviction else []
    if rows:
        pieces.append("\n## Last-24h conviction-name news headlines")
        for title, t, ts in rows:
            pieces.append(f"- [{ts[:10]}] {t}: {title[:90]}")

    return "\n".join(pieces)


_MORNING_NOTE_PROMPT: str = (
    "## 今日晨会笔记 / Morning note\n\n"
    "You are writing a TIGHT 1-page morning note for the boss. Output language: {language}.\n\n"
    "**Research workflow:** Search and reason in **English** — English sources "
    "(SEC, Bloomberg, FactSet, IR, sell-side, English-language news) are far "
    "richer for US/global equities. **Only translate the FINAL note body into "
    "{language}.** Keep tickers, company names, dates, numbers, and URLs in "
    "canonical English/numeric form. Translate prose and section headings. "
    "Exception: A-share / HK names — Chinese disclosures primary.\n\n"
    "Use the structured signals below as INPUT (already pulled from our DB). "
    "Synthesize them into a 5-section markdown note. Be opinionated.\n\n"
    "**VOLUME CONVENTION (boss directive 2026-05-09):** When you cite ANY "
    "volume figure (vs 20-day avg, ratio, etc.), it MUST come from the "
    "'Previous-session FINAL volume' block below -- this is yesterday's 4 PM ET "
    "settled close, fully comparable to a 20-day average of same-time settled "
    "closes. Do NOT cite 'today's volume' or 'intraday volume' -- if today's "
    "session hasn't closed yet, you don't have apples-to-apples data, and "
    "intraday-partial-bars have been a source of bad signals before.\n\n"
    "{context}\n\n"
    "## Required output sections (each ~3-5 bullets max)\n\n"
    "### 1. 头条 / Top call\n"
    "The single most important signal across the conviction list. One ticker, "
    "one sentence on what changed, one sentence on action implication.\n\n"
    "### 2. 隔夜动态 / Overnight developments\n"
    "Specific named events from the last 24h that move the conviction list. "
    "Skip headline noise; cite which name + which signal + what it means.\n\n"
    "### 3. 异常信号 / Anomalies\n"
    "Anything from F12 price anomalies + F36 UOA + F39 AI-loop monitor that "
    "warrants attention. Quantify.\n\n"
    "### 4. 今日日程 / Today's calendar\n"
    "Earnings dates + analyst-day announcements + macro data releases that "
    "impact the conviction list. If none, say so.\n\n"
    "### 5. 操作建议 / Action items (max 3)\n"
    "Specific, named actions. Each: ticker | action (ADD/HOLD/TRIM/EXIT) | "
    "trigger condition | invalidator.\n\n"
    "Keep total length under 600 words. End with: 'Not financial advice.'"
)


def morning_note(*, conn: sqlite3.Connection, language: str = "zh-en") -> SkillReport:
    """Generate today's morning note; persist as research_reports."""
    settings = get_settings()
    try:
        check_cost_ceiling(conn, settings)
        context = _build_morning_context(conn)
        prompt = _MORNING_NOTE_PROMPT.format(language=language, context=context)
        response = _core_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MORNING_NOTE_MAX_TOKENS,
            conn=conn,
            caller="morning_note",
        )
    except (CostCeilingError, Exception):
        logger.exception("morning_note failed")
        return SkillReport(
            ticker=None, kind="morning_note", body="",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    full_body = (
        f"# 晨会笔记 / Morning note -- {today}\n\n"
        f"{(response.content or '').strip()}"
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('morning_note', ?, ?, ?)",
        (f"晨会笔记 {today}", full_body, now),
    )
    conn.commit()
    return SkillReport(
        ticker=None, kind="morning_note", body=full_body,
        research_id=int(cur.lastrowid), created_at=now,
    )
