"""stock.tech_dive -- F43 structured 4-round technology deep-dive engine.

Boss directive 2026-05-06: stop summarizing news, start mining technology
trends. Each dive must close two loops (tech AND business) and surface 3+
public companies in the chain. Boss's canonical example: OCS optical
circuit switching vs CPO -- which should surface Silex (Sweden), 赛微电子
(300456.SZ), 光库科技 (300620.SZ).

Routes through `get_core_client()` so it's free under the operator's
Claude Code subscription. Each dive runs 4 sequential rounds; total
is ~5-15 min wall clock per topic depending on backend latency.

Persisted as a research_reports row (kind='tech_dive') so the daily push
can surface recent dives + the boss can read on the APK.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import CostCeilingError, check_cost_ceiling
from stock.research import _core_chat

logger = logging.getLogger(__name__)

ROUND_MAX_TOKENS: int = 1500
DEFAULT_LANGUAGE: str = "zh-en"

# Canonical 4-round structured prompts. Boss explicitly wants closed-loop
# on tech AND business plus a company chain -- not a summary.
ROUND_PROMPTS: list[tuple[str, str]] = [
    (
        "tech_loop",
        "## Round 1 / 第一轮 -- 技术闭环 / Technology closed loop\n\n"
        "Cover EXACTLY in {language}:\n"
        "1. **What the technology IS** -- one paragraph, concrete, no marketing.\n"
        "2. **What incumbent it challenges** -- name the incumbent (PAM4-DSP, "
        "PEMFC, electrical packet switching, etc.).\n"
        "3. **Pros over the incumbent** -- 3-5 bullets each with a number "
        "(bandwidth %, cost ratio, deployment time, etc.).\n"
        "4. **Cons / unsolved problems** -- 3-5 bullets, the WEAK LINKS. If "
        "you can't name any, the technology is already commoditized.\n"
        "5. **Where it's been validated** -- specific named deployments by "
        "specific operators (e.g. 'Google OCS in Jupiter datacenters since "
        "2022'). Filings/press releases when known.\n"
        "Do NOT cover business/market layers in this round. Do NOT enumerate "
        "companies yet. Just the physics + engineering."
    ),
    (
        "business_loop",
        "## Round 2 / 第二轮 -- 商业闭环 / Business closed loop\n\n"
        "Cover EXACTLY in {language}:\n"
        "1. **Revenue flow** -- who pays whom along the chain (e.g. "
        "hyperscaler -> module vendor -> packaging house -> substrate maker).\n"
        "2. **Unit-economics inflection point** -- when does the new tech "
        "become cheaper per unit-of-output than the incumbent? Cite the cost "
        "delta or break-even volume.\n"
        "3. **Demand magnitude** -- TAM-ish or specific shipment volumes; "
        "cite hyperscaler capex commitments where they exist (Microsoft/Meta/"
        "Google/Amazon $X billion AI capex etc.).\n"
        "4. **Customer concentration risk** -- does the chain depend on 2-3 "
        "buyers? Name them. Quantify their share if known.\n"
        "5. **Time-to-revenue** -- when does the chain start booking real "
        "revenue (not just LOIs / contracts)?\n"
        "Build on the technology you described in Round 1. Stay specific."
    ),
    (
        "company_chain",
        "## Round 3 / 第三轮 -- 链条公司 / Public companies in the chain\n\n"
        "Name AT LEAST 3 PUBLIC COMPANIES with exchange tickers, "
        "preferably across DIFFERENT layers (substrate / device / module / "
        "system / integrator). For each, in {language}:\n\n"
        "- **Ticker + name + exchange** (e.g. `300456.SZ 赛微电子 / Shenzhen ChiNext`)\n"
        "- **Layer in chain** (substrate / MEMS / module / system / etc.)\n"
        "- **Specific product into this trend** (their priced SKU, not "
        "marketing). Include shipment volume or revenue % when known.\n"
        "- **Market cap + scale** (USD or RMB; revenue, employees if known)\n"
        "- **Top 1-2 competitors** in their layer (ticker if public, "
        "name if private; foreign + domestic when relevant)\n"
        "- **Vehicle quality** -- one sentence on why they're a clean "
        "pure-play OR a diversified beneficiary.\n\n"
        "Bonus: name 1-2 PRIVATE companies that are critical-path even if "
        "not investable (often Swedish/Japanese/Korean specialty materials)."
    ),
    (
        "synthesis",
        "## Round 4 / 第四轮 -- 证伪 + 综合判断 / Falsification + synthesis\n\n"
        "Cover EXACTLY in {language}:\n\n"
        "**3-5 falsification triggers** -- specific OBSERVABLE signals "
        "that would prove this trend wrong. Each must be measurable: a "
        "number, a date, an event you can verify in news/filings/disclosures. "
        "'Stock falls' is NOT a falsifier -- name the underlying real-world "
        "signal that would falsify the chain of logic.\n\n"
        "**Synthesis paragraph** (max 200 words):\n"
        "- Is this trend in the 'before-it-20x' zone or already crowded? "
        "Cite the specific evidence behind your read.\n"
        "- The single thing you would watch over the next 90 days to update "
        "conviction (NOT a stock price -- an industry signal).\n"
        "- Which of the public companies in Round 3 is the cleanest entry "
        "right now, and at what level / scenario you would NOT want to own it.\n\n"
        "End with the literal disclaimer: 'Not financial advice.'"
    ),
]


class TechDiveRound(BaseModel):
    """One 1500-token-max round in the structured dive."""

    round_num: int
    label: str  # tech_loop | business_loop | company_chain | synthesis
    output: str


class TechDive(BaseModel):
    """Full 4-round dive with metadata for persistence + rendering."""

    topic: str
    sector: str  # information | biopharma_ai | energy | other
    language: str
    rounds: list[TechDiveRound]
    created_at: str
    research_id: int | None = None


def _build_round_prompt(
    *, topic: str, sector: str, prior: list[TechDiveRound],
    label: str, instructions: str, language: str,
) -> str:
    """Compose the prompt for one round; includes prior-round transcript."""
    history = "\n\n".join(
        f"### Round {r.round_num} ({r.label})\n\n{r.output}"
        for r in prior
    ) or "(No prior rounds; this is round 1.)"
    return (
        f"You are running a STRUCTURED tech-trend deep-dive on this topic:\n\n"
        f"**Topic:** {topic}\n"
        f"**Sector:** {sector} (information / biopharma_ai / energy)\n"
        f"**Output language:** {language}\n\n"
        f"## Prior rounds in this dive\n\n{history}\n\n"
        f"{instructions.format(language=language)}"
    )


def run_tech_dive(
    *, topic: str, sector: str, conn: sqlite3.Connection,
    language: str = DEFAULT_LANGUAGE,
) -> TechDive:
    """Run the 4-round dive; return the assembled TechDive object.

    Per-round exception isolation; CostCeilingError aborts cleanly mid-dive
    and returns whatever rounds completed (so we don't lose work).
    """
    settings = get_settings()
    transcript: list[TechDiveRound] = []

    for i, (label, instructions) in enumerate(ROUND_PROMPTS, start=1):
        try:
            check_cost_ceiling(conn, settings)
            prompt = _build_round_prompt(
                topic=topic, sector=sector, prior=transcript,
                label=label, instructions=instructions, language=language,
            )
            response = _core_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=ROUND_MAX_TOKENS,
                conn=conn,
                caller=f"tech_dive_{sector}_{label}",
            )
        except CostCeilingError:
            logger.warning("Cost ceiling hit during tech_dive round %d (%s)", i, label)
            break
        except Exception:
            logger.exception("tech_dive round %d (%s) failed", i, label)
            break

        body = (response.content or "").strip()
        if not body:
            logger.warning("tech_dive round %d (%s) returned empty body", i, label)
            break
        transcript.append(TechDiveRound(round_num=i, label=label, output=body))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return TechDive(
        topic=topic, sector=sector, language=language,
        rounds=transcript, created_at=now,
    )


def render_markdown(dive: TechDive) -> str:
    """Render the dive as a clean structured markdown report."""
    lines = [
        f"# 技术深挖 / Tech deep-dive: {dive.topic}",
        "",
        f"_Sector: {dive.sector} | Generated: {dive.created_at} | "
        f"Rounds: {len(dive.rounds)}_",
        "",
        "---",
        "",
    ]
    for r in dive.rounds:
        lines.append(r.output)
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def persist(conn: sqlite3.Connection, dive: TechDive) -> int:
    """Insert as research_reports + tech_dive_runs; return research_id."""
    body = render_markdown(dive)
    now = dive.created_at
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('tech_dive', ?, ?, ?)",
        (f"技术深挖: {dive.topic[:80]}", body, now),
    )
    research_id = int(cur.lastrowid)
    dive.research_id = research_id
    conn.execute(
        "INSERT INTO tech_dive_runs"
        " (topic, sector, language, research_id, rounds, cost_usd, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            dive.topic, dive.sector, dive.language,
            research_id, len(dive.rounds), 0.0, now,
        ),
    )
    conn.commit()
    return research_id


def run_and_persist(
    *, topic: str, sector: str, conn: sqlite3.Connection,
    language: str = DEFAULT_LANGUAGE,
) -> TechDive:
    """Convenience: run + persist + return the dive object."""
    dive = run_tech_dive(topic=topic, sector=sector, conn=conn, language=language)
    if dive.rounds:
        persist(conn, dive)
    else:
        logger.warning("tech_dive on '%s' produced 0 rounds; not persisting", topic)
    return dive


def recent_dives(
    conn: sqlite3.Connection, *, days: int = 7, limit: int = 10,
) -> list[dict]:
    """Return recent tech_dive_runs for daily-note background reference."""
    rows = conn.execute(
        "SELECT topic, sector, research_id, rounds, created_at"
        " FROM tech_dive_runs"
        " WHERE created_at >= datetime('now', ?)"
        " ORDER BY created_at DESC LIMIT ?",
        (f"-{int(days)} days", int(limit)),
    ).fetchall()
    return [
        {
            "topic": r[0], "sector": r[1], "research_id": r[2],
            "rounds": r[3], "created_at": r[4],
        }
        for r in rows
    ]
