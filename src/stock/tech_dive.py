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
import re
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel

from stock.config import get_settings
from stock.models import CostCeilingError, check_cost_ceiling
from stock.research import _core_chat

logger = logging.getLogger(__name__)

ROUND_MAX_TOKENS: int = 1500
DEFAULT_LANGUAGE: str = "zh"  # boss-facing -- pure Chinese per 2026-05-18 directive

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
    (
        "chokepoint_score",
        "## Round 5 / 第五轮 -- Chokepoint 5 维评分 / 5-dimension research-priority score\n\n"
        "Distill everything above into a **research-priority score** using the "
        "Chokepoint framework. This is NOT a buy signal -- it ranks how much this "
        "field deserves deeper digging. Score EXACTLY in {language}.\n\n"
        "Score each dimension 0-10 (dimension 5 is a 0 to 10 PENALTY magnitude), "
        "with a 1-2 sentence justification grounded in the rounds above:\n\n"
        "1. **大产业趋势 / Industry trend (weight 25%)** -- is there durable, "
        "multi-year demand behind this direction?\n"
        "2. **供给瓶颈 / Supply bottleneck (weight 25%)** -- {bottleneck_reinterpretation}\n"
        "3. **公司验证 / Company validation (weight 25%)** -- are the Round-3 "
        "companies genuinely in the bottleneck position, with real product/orders, "
        "not just narrative?\n"
        "4. **估值错配 / Valuation mismatch (weight 15%)** -- has the market NOT yet "
        "priced this in? Higher score = more mispriced / more asymmetry left.\n"
        "5. **风险扣分 / Risk deduction (weight -15%)** -- magnitude 0-10 of hard "
        "negatives (customer concentration, uncertain orders, competition, "
        "regulatory, single-point failure). This SUBTRACTS.\n\n"
        "{phase_guidance}"
        "Composite = trend*0.25 + bottleneck*0.25 + validation*0.25 "
        "+ valuation*0.15 - risk*0.15.\n\n"
        "After the per-dimension justifications, emit the score on ONE final line in "
        "EXACTLY this machine-readable format (integers 0-10, composite to 2 decimals):\n\n"
        "SCORES: trend=N bottleneck=N validation=N valuation=N risk=N => composite=F\n\n"
        "End with the literal disclaimer: 'Not financial advice.'"
    ),
]

# Chokepoint weights -- keep in lockstep with the composite formula in the
# Round 5 prompt above. Risk is a deduction (negative weight).
CHOKEPOINT_WEIGHTS: dict[str, float] = {
    "trend": 0.25,
    "bottleneck": 0.25,
    "validation": 0.25,
    "valuation": 0.15,
    "risk": -0.15,
}

# Parses the mandated machine-readable score line from the Round 5 output.
_SCORES_RE = re.compile(
    r"SCORES:\s*trend=(-?\d+(?:\.\d+)?)\s+bottleneck=(-?\d+(?:\.\d+)?)\s+"
    r"validation=(-?\d+(?:\.\d+)?)\s+valuation=(-?\d+(?:\.\d+)?)\s+"
    r"risk=(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


class TechDiveRound(BaseModel):
    """One 1500-token-max round in the structured dive."""

    round_num: int
    label: str  # tech_loop | business_loop | company_chain | synthesis | chokepoint_score
    output: str


class ChokepointScore(BaseModel):
    """Parsed 5-dimension chokepoint research-priority score for one dive."""

    trend: int
    bottleneck: int
    validation: int
    valuation: int
    risk: int
    composite: float


class TechDive(BaseModel):
    """Full structured dive with metadata for persistence + rendering."""

    topic: str
    sector: str  # information | biopharma_ai | energy | ai_demand | space_tech | other
    language: str
    rounds: list[TechDiveRound]
    created_at: str
    research_id: int | None = None
    phase: str | None = None  # early | emerging | mature
    chokepoint: ChokepointScore | None = None


def _clamp_score(value: float) -> int:
    """Clamp a raw dimension score into the 0-10 integer range."""
    return max(0, min(10, int(round(value))))


def _parse_chokepoint_scores(text: str) -> ChokepointScore | None:
    """Extract the mandated `SCORES:` line and recompute the composite server-side.

    The LLM's own composite is advisory only -- we clamp each dimension to 0-10
    and recompute from CHOKEPOINT_WEIGHTS so the stored number is always correct.
    Returns None when no SCORES line is present (the dive still persists).
    """
    matches = list(_SCORES_RE.finditer(text or ""))
    if not matches:
        return None
    m = matches[-1]  # last match wins if the model echoed the format earlier
    trend = _clamp_score(float(m.group(1)))
    bottleneck = _clamp_score(float(m.group(2)))
    validation = _clamp_score(float(m.group(3)))
    valuation = _clamp_score(float(m.group(4)))
    risk = _clamp_score(float(m.group(5)))
    composite = (
        trend * CHOKEPOINT_WEIGHTS["trend"]
        + bottleneck * CHOKEPOINT_WEIGHTS["bottleneck"]
        + validation * CHOKEPOINT_WEIGHTS["validation"]
        + valuation * CHOKEPOINT_WEIGHTS["valuation"]
        + risk * CHOKEPOINT_WEIGHTS["risk"]
    )
    return ChokepointScore(
        trend=trend, bottleneck=bottleneck, validation=validation,
        valuation=valuation, risk=risk, composite=round(composite, 2),
    )


# Buyer-side (ai_demand) reinterprets the "supply bottleneck" dimension as a
# moat/defensibility test -- there is no physical supply chokepoint, the question
# is whether the company can keep the value AI creates instead of competing it away.
_BOTTLENECK_SUPPLY = (
    "is this link irreplaceable / hard to expand / hard to substitute? A true "
    "chokepoint scores high; a commodity layer scores low."
)
_BOTTLENECK_MOAT = (
    "this is the BUYER side, so score moat / defensibility instead of physical "
    "supply: proprietary data, distribution, switching costs, and workflow "
    "lock-in that let this company KEEP the value AI creates instead of "
    "competing it away. A durable moat scores high; an easily-copied AI feature "
    "scores low."
)

# Early/emerging fields (space, pre-revenue biopharma, new AI-demand names) must
# not be scored like mature caps. Guidance is empty for mature fields.
_PHASE_GUIDANCE_EARLY = (
    "**Phase = {phase} (early-stage).** Score Company validation (3) and "
    "Valuation mismatch (4) on an OPTION-VALUE basis: judge proof-of-concept, "
    "milestones, and optionality, NOT trailing revenue or earnings multiples. "
    "Do NOT penalize a pre-revenue name the way you would a mature-cap miss, and "
    "explicitly flag that this score carries HIGH VARIANCE.\n\n"
)


def _phase_guidance(phase: str | None) -> str:
    """Return the early-phase scoring guidance block, or '' for mature fields."""
    if phase and phase.strip().lower() in {"early", "emerging"}:
        return _PHASE_GUIDANCE_EARLY.format(phase=phase.strip().lower())
    return ""


def _build_round_prompt(
    *, topic: str, sector: str, prior: list[TechDiveRound],
    label: str, instructions: str, language: str, phase: str | None = None,
) -> str:
    """Compose the prompt for one round; includes prior-round transcript."""
    history = "\n\n".join(
        f"### Round {r.round_num} ({r.label})\n\n{r.output}"
        for r in prior
    ) or "(No prior rounds; this is round 1.)"
    is_buyer_side = sector == "ai_demand"
    bottleneck_reinterpretation = _BOTTLENECK_MOAT if is_buyer_side else _BOTTLENECK_SUPPLY
    phase_guidance = _phase_guidance(phase)
    rendered_instructions = instructions.format(
        language=language,
        bottleneck_reinterpretation=bottleneck_reinterpretation,
        phase_guidance=phase_guidance,
    )
    return (
        f"You are running a STRUCTURED tech-trend deep-dive on this topic:\n\n"
        f"**Topic:** {topic}\n"
        f"**Sector:** {sector} (information / biopharma_ai / energy / ai_demand / space_tech)\n"
        f"**Output language:** {language}\n\n"
        f"**Research workflow:** Search and reason in **English** — English "
        f"sources (papers, IEEE, SemiAnalysis, IR pages, sell-side, FT/WSJ) are "
        f"far richer for tech-trend analysis. **Only translate the FINAL "
        f"deliverable body into {language}.** Keep technical terms, company "
        f"names, paper titles, model names, dates, and URLs in canonical form. "
        f"Exception: A-share / HK Chinese names — Chinese disclosures are "
        f"primary source.\n\n"
        f"## Prior rounds in this dive\n\n{history}\n\n"
        f"{rendered_instructions}"
    )


def run_tech_dive(
    *, topic: str, sector: str, conn: sqlite3.Connection,
    language: str = DEFAULT_LANGUAGE, phase: str | None = None,
) -> TechDive:
    """Run the structured multi-round dive; return the assembled TechDive object.

    Per-round exception isolation; CostCeilingError aborts cleanly mid-dive
    and returns whatever rounds completed (so we don't lose work). The final
    `chokepoint_score` round is parsed into TechDive.chokepoint when present.
    """
    settings = get_settings()
    transcript: list[TechDiveRound] = []

    for i, (label, instructions) in enumerate(ROUND_PROMPTS, start=1):
        try:
            check_cost_ceiling(conn, settings)
            prompt = _build_round_prompt(
                topic=topic, sector=sector, prior=transcript,
                label=label, instructions=instructions, language=language,
                phase=phase,
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

    # Parse the chokepoint score out of the final round if it ran.
    chokepoint: ChokepointScore | None = None
    for r in transcript:
        if r.label == "chokepoint_score":
            chokepoint = _parse_chokepoint_scores(r.output)
            break

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return TechDive(
        topic=topic, sector=sector, language=language,
        rounds=transcript, created_at=now, phase=phase, chokepoint=chokepoint,
    )


def render_markdown(dive: TechDive) -> str:
    """Render the dive as a clean structured markdown report."""
    meta = (
        f"_Sector: {dive.sector} | Generated: {dive.created_at} | "
        f"Rounds: {len(dive.rounds)}_"
    )
    lines = [
        f"# 技术深挖 / Tech deep-dive: {dive.topic}",
        "",
        meta,
    ]
    if dive.chokepoint is not None:
        phase_tag = f", phase={dive.phase}" if dive.phase else ""
        lines.append("")
        lines.append(
            f"**研究优先级 / Chokepoint composite: {dive.chokepoint.composite:.2f}"
            f"{phase_tag}** "
            f"(趋势 {dive.chokepoint.trend} · 瓶颈 {dive.chokepoint.bottleneck} · "
            f"验证 {dive.chokepoint.validation} · 估值 {dive.chokepoint.valuation} · "
            f"风险 -{dive.chokepoint.risk})"
        )
    lines.extend(["", "---", ""])
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
    cp = dive.chokepoint
    conn.execute(
        "INSERT INTO tech_dive_runs"
        " (topic, sector, language, research_id, rounds, cost_usd, created_at,"
        "  phase, score_trend, score_bottleneck, score_validation,"
        "  score_valuation, score_risk, score_composite)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dive.topic, dive.sector, dive.language,
            research_id, len(dive.rounds), 0.0, now,
            dive.phase,
            cp.trend if cp else None,
            cp.bottleneck if cp else None,
            cp.validation if cp else None,
            cp.valuation if cp else None,
            cp.risk if cp else None,
            cp.composite if cp else None,
        ),
    )
    conn.commit()
    return research_id


def run_and_persist(
    *, topic: str, sector: str, conn: sqlite3.Connection,
    language: str = DEFAULT_LANGUAGE, phase: str | None = None,
) -> TechDive:
    """Convenience: run + persist + return the dive object."""
    dive = run_tech_dive(
        topic=topic, sector=sector, conn=conn, language=language, phase=phase,
    )
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


def top_chokepoint_dives(
    conn: sqlite3.Connection, *, days: int = 21, limit: int = 8,
) -> list[dict]:
    """Return recent dives ranked by chokepoint composite (highest first).

    Only rows with a non-NULL score_composite are returned, so a leaderboard
    of fields by research priority. Separate from recent_dives so its callers
    and tests stay independent.
    """
    rows = conn.execute(
        "SELECT topic, sector, phase, score_composite, score_trend,"
        " score_bottleneck, score_validation, score_valuation, score_risk,"
        " research_id, created_at"
        " FROM tech_dive_runs"
        " WHERE created_at >= datetime('now', ?) AND score_composite IS NOT NULL"
        " ORDER BY score_composite DESC, created_at DESC LIMIT ?",
        (f"-{int(days)} days", int(limit)),
    ).fetchall()
    return [
        {
            "topic": r[0], "sector": r[1], "phase": r[2], "composite": r[3],
            "trend": r[4], "bottleneck": r[5], "validation": r[6],
            "valuation": r[7], "risk": r[8], "research_id": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


def format_chokepoint_leaderboard_block(
    conn: sqlite3.Connection, *, days: int = 21, limit: int = 8,
) -> str:
    """Render the cross-field chokepoint leaderboard for the daily research note.

    Returns '' when no scored dives exist so the caller can substitute a
    placeholder. Mirrors the formatter pattern used by ai_loop_monitor.
    """
    rows = top_chokepoint_dives(conn, days=days, limit=limit)
    if not rows:
        return ""
    lines = [
        "跨领域研究优先级 / Cross-field research-priority (Chokepoint 5-dim, "
        f"last {days}d):",
    ]
    for i, r in enumerate(rows, start=1):
        phase = f" [{r['phase']}]" if r.get("phase") else ""
        topic = (r["topic"] or "")[:70]
        lines.append(
            f"{i}. {r['composite']:.2f} | {r['sector']}{phase} | {topic} "
            f"(趋势{r['trend']}/瓶颈{r['bottleneck']}/验证{r['validation']}/"
            f"估值{r['valuation']}/风险-{r['risk']})"
        )
    return "\n".join(lines)
