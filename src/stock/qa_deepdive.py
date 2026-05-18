"""stock.qa_deepdive -- F37 progressive Q&A deep-dive engine.

Boss directive 2026-05-05: "他看到答案之后，他自己能够继续发问题，就像我一样，
用 QA 这种逻辑." Build a research mode that drills into a ticker by asking
itself follow-up questions, each one going deeper than the last.

Shape of one run:

  Q1: "Why is <ticker> investable RIGHT NOW, not 6 months ago or 6 months from now?"
  A1: <LLM answer, ~150 words>
  Q2: <LLM-generated follow-up that interrogates the weakest link in A1>
  A2: ...
  Q3: <follow-up to A2>
  ...
  Q_final: "Given everything above, what must be true for this thesis to fail?
            Name 3 specific observable indicators that would invalidate it."

Output: a structured QADeepDive with rounds, persisted as research_reports
kind='deep_qa'. Reads cleanly as a Q&A transcript -- the boss can read top-to-
bottom and see the logic chain.

Cost discipline:
* Each round = one Claude call (the answer + the next question, in one prompt)
* Default 5 rounds = 5 calls. Bounded by max_rounds.
* Cost ceiling check before EACH round; abort cleanly if hit.
* Caller-name tagged with f"qa_deepdive_{ticker}" so cost shows up in llm_calls.
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

DEFAULT_ROUNDS: int = 5
MAX_ROUNDS: int = 8
ANSWER_MAX_TOKENS: int = 700  # ~500 words per answer is plenty
MIN_QUESTION_LENGTH: int = 10  # reject malformed empty/short follow-ups


class QARound(BaseModel):
    """One Q-A pair in the chain."""

    round_num: int
    question: str
    answer: str


class QADeepDive(BaseModel):
    """Full Q&A transcript with metadata for persistence + rendering."""

    ticker: str
    seed_thesis: str
    rounds: list[QARound]
    created_at: str
    research_id: int | None = None


def _opening_question(ticker: str, seed_thesis: str) -> str:
    """The first question is fixed -- timing-of-thesis interrogation."""
    if seed_thesis:
        return (
            f"For {ticker}, the operator is considering this thesis: "
            f"'{seed_thesis.strip()}'. Why is this investable RIGHT NOW, not "
            f"6 months ago or 6 months from now? What is the specific catalyst "
            f"window, and which observable evidence makes the timing tight?"
        )
    return (
        f"For {ticker}, why is this investable RIGHT NOW, not 6 months ago "
        f"or 6 months from now? What concrete catalyst makes the next "
        f"3-9 months the right window, and what observable evidence supports it?"
    )


def _final_question() -> str:
    """The last round asks for invalidation criteria -- forces falsifiable thesis."""
    return (
        "Given everything you've established above, name 3 SPECIFIC observable "
        "indicators that would invalidate this thesis. Each must be measurable "
        "(a number, a date, an event you can confirm). 'The stock falls' is NOT "
        "an indicator -- name the underlying real-world signal that would falsify "
        "the chain of logic, not the symptom."
    )


def _build_round_prompt(
    ticker: str,
    transcript_so_far: list[QARound],
    next_question: str,
    is_final: bool,
    language: str = "zh",
) -> str:
    """Compose the prompt for one round.

    Includes the full transcript so the LLM can see what's been established
    and avoid repeating itself; ends with the new question and instructions
    for shape (length, citation discipline, follow-up generation).

    The language directive at the top binds output to Chinese by default --
    F37 dives are boss-facing artifacts; English seed theses (e.g. operator-
    written) must not change the answer language.
    """
    history_blocks: list[str] = []
    for r in transcript_so_far:
        history_blocks.append(f"### Q{r.round_num}: {r.question}\n\n{r.answer}")
    history = "\n\n".join(history_blocks) if history_blocks else "(No prior rounds.)"

    follow_up_directive = (
        ""
        if is_final
        else (
            "\n\nAFTER your answer, on a new line, write exactly:\n\n"
            "  NEXT_QUESTION: <one specific follow-up question that drills "
            "into the WEAKEST or LEAST-EVIDENCED claim in the answer above>.\n\n"
            "The follow-up must be specific -- name the thing to verify, the "
            "number to check, or the assumption to test. Don't ask 'what about "
            "competition' -- ask 'what does ASML's most recent quarterly "
            "shipment to SMIC tell us about the foundry timeline'."
        )
    )

    return (
        f"**Research workflow:** Conduct ALL web searches, source-gathering, and "
        f"analytical reasoning in **English** — English-language sources (SEC "
        f"filings, Bloomberg, FactSet, company IR pages, sell-side notes) are "
        f"dramatically richer than Chinese-language sources for US and global "
        f"equities. Reason in English internally. **Only translate the FINAL "
        f"answer body and the NEXT_QUESTION line into {language}.** Keep ticker "
        f"symbols, company names, model names, dates, numbers, and URLs in "
        f"their canonical English/numeric form. Translate only the prose and "
        f"section headings. Exception: {ticker} is an A-share or HK-listed "
        f"Chinese name — search Chinese-language disclosures (Eastmoney, "
        f"巨潮资讯) as the primary source for those.\n\n"
        f"You are doing a deep-dive Q&A research session on {ticker}. The boss's "
        f"explicit instruction: dig deep, see what most people don't see, build "
        f"self-consistent logic, and after each answer ask yourself the next "
        f"follow-up question. Each answer should be 150-300 words, cite specific "
        f"numbers/filings/dates when possible, and be willing to say '我不知道' "
        f"rather than fill space.\n\n"
        f"## Transcript so far\n\n{history}\n\n"
        f"## Now answer this question\n\n"
        f"### Q{len(transcript_so_far) + 1}: {next_question}\n\n"
        f"{follow_up_directive}"
    )


_NEXT_Q_RE = re.compile(
    r"NEXT_QUESTION\s*:\s*(.+?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE,
)


def _parse_answer_and_followup(text: str) -> tuple[str, str | None]:
    """Split an LLM response into (answer_body, next_question_or_None)."""
    match = _NEXT_Q_RE.search(text)
    if not match:
        return text.strip(), None
    next_q = match.group(1).strip()
    answer = text[: match.start()].strip()
    if len(next_q) < MIN_QUESTION_LENGTH:
        return answer, None
    return answer, next_q


def run_qa_deepdive(
    *, ticker: str, seed_thesis: str, conn: sqlite3.Connection,
    rounds: int = DEFAULT_ROUNDS,
    language: str | None = None,
) -> QADeepDive:
    """Run a Q&A chain; return the full transcript.

    Each round generates the answer to the current question PLUS the next
    question (except the final round, which asks for invalidation criteria).
    If the LLM fails to produce a NEXT_QUESTION line, we substitute a generic
    drill-down question rather than abort -- some progress is better than none.

    `language` defaults to settings.research_language (zh). F37 dives are
    boss-facing; we bind output language explicitly so operator-written
    English seed theses don't flip the answer language.
    """
    rounds = max(2, min(int(rounds), MAX_ROUNDS))
    settings = get_settings()
    lang = (language or settings.research_language or "zh").strip() or "zh"
    transcript: list[QARound] = []
    current_q = _opening_question(ticker, seed_thesis)

    for i in range(1, rounds + 1):
        is_final = i == rounds
        try:
            check_cost_ceiling(conn, settings)
            prompt = _build_round_prompt(
                ticker, transcript, current_q, is_final=is_final, language=lang,
            )
            response = _core_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=ANSWER_MAX_TOKENS,
                conn=conn,
                caller=f"qa_deepdive_{ticker}_round{i}",
            )
        except CostCeilingError:
            logger.warning("Cost ceiling hit during QA round %d; stopping early", i)
            break

        body = (response.content or "").strip()
        if not body:
            logger.warning("Empty answer in QA round %d; stopping", i)
            break
        answer, next_q = _parse_answer_and_followup(body)
        transcript.append(QARound(round_num=i, question=current_q, answer=answer))

        if is_final:
            break
        if next_q:
            current_q = next_q
        elif i + 1 == rounds:
            current_q = _final_question()
        else:
            current_q = (
                f"What is the strongest counter-argument against the position "
                f"taken in answer Q{i}? Name the most credible bear case and "
                f"what specific evidence would resolve it either way."
            )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return QADeepDive(
        ticker=ticker.upper(),
        seed_thesis=seed_thesis,
        rounds=transcript,
        created_at=now,
    )


def render_markdown(dive: QADeepDive) -> str:
    """Render a QADeepDive as a clean Q&A markdown transcript."""
    lines = [
        f"# {dive.ticker} 深度问答 / Q&A deep-dive",
        f"",
        f"_Generated {dive.created_at} -- {len(dive.rounds)} rounds_",
        "",
    ]
    if dive.seed_thesis:
        lines.append(f"**Seed thesis**: {dive.seed_thesis}")
        lines.append("")
    for r in dive.rounds:
        lines.append(f"## Q{r.round_num}: {r.question}")
        lines.append("")
        lines.append(r.answer)
        lines.append("")
    return "\n".join(lines)


def persist(conn: sqlite3.Connection, dive: QADeepDive) -> int:
    """Insert as research_reports kind='deep_qa'; return the new id."""
    body = render_markdown(dive)
    now = dive.created_at
    cur = conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('deep_qa', ?, ?, ?)",
        (f"{dive.ticker} 深度问答", body, now),
    )
    conn.commit()
    research_id = int(cur.lastrowid)
    dive.research_id = research_id
    return research_id


def run_and_persist(
    *, ticker: str, seed_thesis: str = "", conn: sqlite3.Connection,
    rounds: int = DEFAULT_ROUNDS,
) -> QADeepDive:
    """Convenience: run the chain, persist, return the dive object."""
    dive = run_qa_deepdive(
        ticker=ticker, seed_thesis=seed_thesis, conn=conn, rounds=rounds,
    )
    if dive.rounds:
        persist(conn, dive)
    else:
        logger.warning("Q&A deep-dive for %s produced 0 rounds; not persisting", ticker)
    return dive
