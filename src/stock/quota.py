"""stock.quota -- CLI-session quota windows + leftover-job retry (plan I).

Codex/Claude CLI are subscription backends whose usage limits work on a
~5-hour session window. When codex hits its cap, F17c falls back to claude_cli
for a 30-minute cooldown -- but if both are exhausted, the work of that cycle
was simply LOST until the next scheduled fire (which for a weekly dive is a
week away). The broker positions pull was down June 4-10 for exactly this
reason and nobody could see it.

This module makes quota exhaustion a first-class, recoverable event:

1. `record_usage_limit_event` -- persisted by models.py whenever the F17c
   credit-limit detector trips (provider, caller, when).
2. `usage_windows` / `format_windows_report` -- bucket llm_calls into fixed
   5-hour UTC windows per provider so `stock usage --windows` shows how much
   of the current window each backend has consumed and when it refreshes.
3. `leftover_jobs_due` -- map exhaustion events (and job_runs errors that look
   credit-shaped, e.g. the broker pull) back to scheduler job ids; once the
   5-hour window has refreshed, the orchestrator's `retry_quota_leftovers`
   job re-runs them, capped and deduped.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

WINDOW_HOURS: int = 5
WINDOW_SECS: int = WINDOW_HOURS * 3600
EVENT_MAX_AGE_HOURS: int = 24
MAX_RETRIES_PER_DAY: int = 2

# Scheduler jobs worth re-running after a quota refresh. Plumbing jobs that
# refire within minutes anyway (sync, feedback, alerts, imports) are excluded.
RETRY_ALLOWLIST: frozenset[str] = frozenset({
    "ingest_and_extract", "run_predictions",
    "research_push_morning", "research_push_evening",
    "macro_digest", "score_daily", "thesis_verify", "grade_and_reply",
    "verify_tracked_events", "action_queue_runner",
    "weekly_qa_dive", "weekly_tech_dive", "health_check_weekly",
    "company_dd_dive", "discovery_engine",
    "web_discovery_morning", "web_discovery_evening",
    "daily_self_review", "reflect_weekly",
    "broker_positions_pull", "insiders_pull", "weekly_entry_scan",
    "ai_loop_measure", "smallcap_scan", "uoa_scan",
})

# llm_calls caller prefix -> scheduler job id. Ordered: first match wins, so
# more specific prefixes go first. "@hour" entries pick morning/evening by the
# event's UTC hour (the twice-daily jobs share one code path).
_CALLER_JOB_PREFIXES: tuple[tuple[str, str], ...] = (
    ("thesis.verify", "thesis_verify"),
    ("thesis.", "run_predictions"),          # extract runs inside the predict cycle
    ("features.", "ingest_and_extract"),
    ("predict.", "run_predictions"),
    ("events.verify", "verify_tracked_events"),
    ("prompt_rewriter.", "grade_and_reply"),
    ("grading.", "grade_and_reply"),
    ("research.generate_daily", "@research_push"),
    ("research.generate_deep_dive", "action_queue_runner"),
    ("research.generate_health_check", "health_check_weekly"),
    ("macro.", "macro_digest"),
    ("discover.", "@web_discovery"),
    ("learn.reflect_weekly", "reflect_weekly"),
    ("qa_deepdive", "weekly_qa_dive"),
    ("tech_dive", "weekly_tech_dive"),
    ("self_review", "daily_self_review"),
)

_MORNING_CUTOFF_HOUR_UTC: int = 8  # 02:xx batch = morning, 14:xx batch = evening


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_usage_limit_event(
    conn: sqlite3.Connection,
    provider: str,
    caller: str,
    *,
    detail: str | None = None,
) -> None:
    """Persist one quota-exhaustion detection. Called from models.py F17c."""
    conn.execute(
        "INSERT INTO usage_limit_events (provider, caller, detail, detected_at)"
        " VALUES (?, ?, ?, ?)",
        (provider, caller, (detail or "")[:300] or None,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def map_caller_to_job(caller: str, detected_at: datetime) -> str | None:
    """Map an llm_calls caller string to the scheduler job that drives it."""
    base = str(caller or "").strip()
    for prefix, job_id in _CALLER_JOB_PREFIXES:
        if not base.startswith(prefix):
            continue
        if job_id == "@research_push":
            return (
                "research_push_morning"
                if detected_at.hour < _MORNING_CUTOFF_HOUR_UTC
                else "research_push_evening"
            )
        if job_id == "@web_discovery":
            return (
                "web_discovery_morning"
                if detected_at.hour < _MORNING_CUTOFF_HOUR_UTC
                else "web_discovery_evening"
            )
        return job_id
    return None


def _retry_count_24h(conn: sqlite3.Connection, job_id: str, now: datetime) -> int:
    cutoff = (now - timedelta(hours=24)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM job_runs"
        " WHERE job_id = ? AND trigger = 'quota_retry' AND finished_at >= ?",
        (job_id, cutoff),
    ).fetchone()
    return int(row[0]) if row else 0


def _succeeded_since(
    conn: sqlite3.Connection, job_id: str, since_iso: str
) -> bool:
    """True if the job already ran ok (scheduled) after the exhaustion event --
    the next regular fire recovered the work, so no retry is needed."""
    row = conn.execute(
        "SELECT 1 FROM job_runs"
        " WHERE job_id = ? AND status = 'ok' AND trigger = 'scheduled'"
        " AND finished_at > ? LIMIT 1",
        (job_id, since_iso),
    ).fetchone()
    return row is not None


def _credit_shaped(text: str) -> bool:
    from stock.models import _CODEX_CREDIT_LIMIT_RE

    return bool(_CODEX_CREDIT_LIMIT_RE.search(text or ""))


def leftover_jobs_due(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[str]:
    """Return job ids whose quota-killed work is ready to retry.

    Due = an unretried usage_limit_event (or a credit-shaped job_runs error)
    older than WINDOW_HOURS (quota refreshed) but younger than 24h, mapped to
    an allowlisted job that has NOT already succeeded since, with fewer than
    MAX_RETRIES_PER_DAY quota retries in the last 24h.
    """
    now = now or datetime.now(timezone.utc)
    refresh_cutoff = now - timedelta(hours=WINDOW_HOURS)
    age_cutoff = now - timedelta(hours=EVENT_MAX_AGE_HOURS)

    candidates: dict[str, str] = {}  # job_id -> earliest trigger timestamp

    for caller, detected_at in conn.execute(
        "SELECT caller, detected_at FROM usage_limit_events"
        " WHERE retried_at IS NULL AND detected_at >= ? AND detected_at <= ?",
        (age_cutoff.isoformat(), refresh_cutoff.isoformat()),
    ):
        ts = _parse_ts(detected_at)
        if ts is None:
            continue
        job_id = map_caller_to_job(str(caller), ts)
        if job_id is None:
            continue
        if job_id not in candidates or detected_at < candidates[job_id]:
            candidates[job_id] = str(detected_at)

    # Second source: jobs whose recorded job_runs error looks credit-shaped
    # (e.g. broker_positions_pull embeds the codex stderr in its error text).
    for job_id, finished_at, error in conn.execute(
        "SELECT job_id, finished_at, error FROM job_runs"
        " WHERE status = 'error' AND trigger = 'scheduled'"
        " AND finished_at >= ? AND finished_at <= ?",
        (age_cutoff.isoformat(), refresh_cutoff.isoformat()),
    ):
        if not _credit_shaped(str(error or "")):
            continue
        if job_id not in candidates or finished_at < candidates[job_id]:
            candidates[str(job_id)] = str(finished_at)

    due: list[str] = []
    for job_id, since_iso in sorted(candidates.items(), key=lambda kv: kv[1]):
        if job_id not in RETRY_ALLOWLIST:
            continue
        if _succeeded_since(conn, job_id, since_iso):
            mark_job_events_retried(conn, job_id, now=now, note="recovered")
            continue
        if _retry_count_24h(conn, job_id, now) >= MAX_RETRIES_PER_DAY:
            continue
        due.append(job_id)
    return due


def mark_job_events_retried(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    now: datetime | None = None,
    note: str = "",
) -> None:
    """Stamp retried_at on all open events that map to job_id."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat() + (f" ({note})" if note else "")
    rows = conn.execute(
        "SELECT id, caller, detected_at FROM usage_limit_events"
        " WHERE retried_at IS NULL",
    ).fetchall()
    ids = []
    for event_id, caller, detected_at in rows:
        ts = _parse_ts(detected_at)
        if ts is not None and map_caller_to_job(str(caller), ts) == job_id:
            ids.append(int(event_id))
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE usage_limit_events SET retried_at = ? WHERE id IN ({placeholders})",
            (stamp, *ids),
        )
        conn.commit()


# --- 5h window monitoring ----------------------------------------------------

def usage_windows(
    conn: sqlite3.Connection, *, days: int = 2
) -> list[dict[str, Any]]:
    """Bucket llm_calls into fixed 5-hour UTC windows per provider, newest first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    buckets: dict[tuple[int, str], dict[str, Any]] = {}
    for created_at, provider, in_tok, out_tok in conn.execute(
        "SELECT created_at, provider, input_tokens, output_tokens FROM llm_calls"
        " WHERE created_at >= ?",
        (cutoff,),
    ):
        ts = _parse_ts(str(created_at))
        if ts is None:
            continue
        bucket = int(ts.timestamp()) // WINDOW_SECS
        key = (bucket, str(provider))
        slot = buckets.setdefault(key, {
            "window_start": datetime.fromtimestamp(
                bucket * WINDOW_SECS, tz=timezone.utc,
            ).isoformat(),
            "provider": str(provider),
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
        })
        slot["calls"] += 1
        slot["input_tokens"] += int(in_tok or 0)
        slot["output_tokens"] += int(out_tok or 0)
    return sorted(
        buckets.values(),
        key=lambda s: (s["window_start"], s["provider"]),
        reverse=True,
    )


def latest_limit_events(
    conn: sqlite3.Connection, *, days: int = 2
) -> list[dict[str, Any]]:
    """Most recent exhaustion event per provider, with the refresh ETA."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out: list[dict[str, Any]] = []
    for provider, detected_at, caller in conn.execute(
        "SELECT provider, MAX(detected_at), caller FROM usage_limit_events"
        " WHERE detected_at >= ? GROUP BY provider",
        (cutoff,),
    ):
        ts = _parse_ts(str(detected_at))
        refresh = (ts + timedelta(hours=WINDOW_HOURS)).isoformat() if ts else None
        out.append({
            "provider": str(provider), "detected_at": str(detected_at),
            "caller": str(caller), "refresh_eta": refresh,
        })
    return out


def format_windows_report(conn: sqlite3.Connection, *, days: int = 2) -> str:
    """`stock usage --windows` body: 5h-window consumption + refresh ETAs."""
    windows = usage_windows(conn, days=days)
    if not windows:
        return f"No LLM calls in the last {days} day(s)."
    now_bucket = int(datetime.now(timezone.utc).timestamp()) // WINDOW_SECS
    lines = [
        f"LLM usage by {WINDOW_HOURS}h UTC window -- last {days} day(s)",
        "(subscription quotas refresh on a ~5-hour session window)", "",
    ]
    for w in windows:
        start = _parse_ts(w["window_start"])
        marker = "  <-- current" if (
            start and int(start.timestamp()) // WINDOW_SECS == now_bucket
        ) else ""
        start_s = start.strftime("%m-%d %H:%M") if start else "?"
        lines.append(
            f"  {start_s}+{WINDOW_HOURS}h  {w['provider']:<12} {w['calls']:>5} calls"
            f"  in {w['input_tokens']:>9,}  out {w['output_tokens']:>8,}{marker}"
        )
    events = latest_limit_events(conn, days=days)
    if events:
        lines.append("")
        lines.append("Usage-limit events:")
        for e in events:
            lines.append(
                f"  {e['provider']}: hit at {e['detected_at'][:16]}"
                f" (caller {e['caller']}), window refresh ~{str(e['refresh_eta'])[:16]}"
            )
    else:
        lines.append("")
        lines.append("No usage-limit events recorded in this period.")
    return "\n".join(lines)
