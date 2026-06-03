"""stock.orchestrator -- scheduled job runner for the prediction pipeline."""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openai
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel

from stock import (
    action_queue,
    ai_loop_monitor,
    alerts,
    anomaly,
    backup,
    broker_sync,
    conversation,
    discovery_engine,
    emailer,
    entry_signals,
    events,
    grading,
    holdings,
    intent,
    prompt_rewriter,
    self_review,
    smallcap_scanner,
    tech_dive,
    thesis,
    warning_dashboard,
)
from stock import options as options_module
from stock.cloud_sync import run_local_sync
from stock.config import get_settings
from stock.db import get_conn
from stock.discover import run_discovery
from stock.features import extract_features
from stock.ingest import fetch_news, fetch_prices
from stock.ingest.insiders import persist_insiders
from stock.learn import reflect_weekly
from stock.models import CostCeilingError
from stock.predict import predict_ticker
from stock.research import (
    generate_daily_research,
    generate_health_check,
    generate_reply,
)
from stock.score import score_due
from stock.websearch import WebSearchUnavailable
from stock.wechat_inbox import pull_chat_screenshots, read_feedback_entries

logger = logging.getLogger(__name__)

WATCHLIST_PATH: str = "data/watchlist.yaml"
MARKET_HOURS_START: int = 14
MARKET_HOURS_END: int = 21
SCORE_HOUR: int = 21
SCORE_MINUTE: int = 30
REFLECT_DAY: str = "sat"
REFLECT_HOUR: int = 6
# Twice-daily research push (UTC). Beijing = UTC+8.
# Morning push: 02:30 UTC = 10:30 Beijing
# Evening push: 14:30 UTC = 22:30 Beijing
RESEARCH_MORNING_HOUR: int = 2
RESEARCH_MORNING_MINUTE: int = 30
RESEARCH_EVENING_HOUR: int = 14
RESEARCH_EVENING_MINUTE: int = 30
# Web discovery fires 30 min before each push so fresh extractions are in the prompt
# Discovery morning: 02:00 UTC = 10:00 Beijing
# Discovery evening: 14:00 UTC = 22:00 Beijing
DISCOVERY_MORNING_HOUR: int = 2
DISCOVERY_MORNING_MINUTE: int = 0
DISCOVERY_EVENING_HOUR: int = 14
DISCOVERY_EVENING_MINUTE: int = 0


class ScheduleInfo(BaseModel):
    """Next-run times for all scheduled jobs."""

    jobs: list[dict[str, str]]


def _get_active_tickers(conn: sqlite3.Connection) -> list[str]:
    """Load active tickers from the watchlist table, falling back to YAML.

    NARROW universe: this is what the prediction job consumes (LLM call per
    ticker = real cost). Stays AI-supply-chain focused.
    """
    # Query the DB watchlist for active tickers
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE active = 1 ORDER BY ticker"
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    # Fall back to the YAML watchlist file
    path = Path(WATCHLIST_PATH)
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("tickers"), list):
            return [str(t).upper() for t in raw["tickers"] if t]

    return []


def _get_ingest_universe(conn: sqlite3.Connection) -> list[str]:
    """WIDE universe for price + news ingestion (no LLM cost per ticker).

    Combines:
      - active watchlist (predictions universe)
      - active holdings (boss's positions -- need price for stop-loss + P&L)
      - secular theme tickers (F25; non-AI long-horizon names that need price
        history for the stop-loss reference table)

    Used by _job_ingest_and_extract so EVERY ticker the daily research note
    might mention has fresh price + news, not just the AI watchlist.
    """
    seen: list[str] = list(_get_active_tickers(conn))
    seen_set = {t for t in seen}

    # Active holdings -- always ingest
    try:
        for h in holdings.list_holdings(conn, active_only=True):
            t = h.ticker.upper()
            if t not in seen_set:
                seen.append(t)
                seen_set.add(t)
    except Exception:
        logger.exception("ingest_universe: holdings lookup failed (non-fatal)")

    # F25 secular theme tickers
    try:
        from stock.secular import all_secular_tickers
        for t in all_secular_tickers():
            t = t.upper()
            if t not in seen_set:
                seen.append(t)
                seen_set.add(t)
    except Exception:
        logger.exception("ingest_universe: secular lookup failed (non-fatal)")

    return seen


def _job_ingest_and_extract() -> None:
    """Fetch news, prices, extract features, then scan active holdings for sell-triggers.

    Uses the WIDE ingest universe (watchlist + holdings + secular themes) so
    every ticker the daily research note might mention has fresh price + news
    history. LLM-cost feature extraction still only fires on watchlist members.
    """
    conn = get_conn()
    try:
        tickers = _get_ingest_universe(conn)
        if not tickers:
            logger.warning("No tickers in ingest universe, skipping")
            return
        watchlist_set = set(_get_active_tickers(conn))

        for ticker in tickers:
            try:
                # Pull fresh news from Yahoo + RSS feeds
                fetch_news(ticker, conn)

                # Pull latest daily OHLCV bars
                fetch_prices(ticker, conn)

                # Extract features ONLY for the predict universe (LLM-priced).
                # Secular + holdings tickers ride along for price/news without
                # burning LLM cost per ticker.
                if ticker in watchlist_set:
                    extract_features(ticker, conn)
            except CostCeilingError:
                logger.warning("Cost ceiling reached during ingest, stopping")
                return
            except Exception:
                logger.exception("Ingest/extract failed for %s", ticker)

        # F28: after fresh news lands, scan active holdings for sell-trigger
        # keywords (margin compression, compliance events, price wars, etc.)
        # and write a kind='alert' note if anything fires. Best-effort.
        try:
            alert_counts = alerts.scan_all_holdings(conn)
            if alert_counts:
                summary = ", ".join(f"{t}={n}" for t, n in alert_counts.items())
                logger.info("Holding alerts fired this tick: %s", summary)
        except Exception:
            logger.exception("Holding sell-trigger scan failed (non-fatal)")
    finally:
        conn.close()


def _job_run_predictions() -> None:
    """Run prediction cycle for all watchlist tickers."""
    conn = get_conn()
    try:
        tickers = _get_active_tickers(conn)
        if not tickers:
            logger.warning("No active tickers in watchlist, skipping predictions")
            return

        for ticker in tickers:
            try:
                result = predict_ticker(ticker, conn)
                logger.info(
                    "Predicted %s %s (prob_up=%.2f, cal=%.2f)",
                    result.ticker,
                    result.direction,
                    result.prob_up,
                    result.prob_up_calibrated or result.prob_up,
                )
            except CostCeilingError:
                logger.warning("Cost ceiling reached during prediction, stopping")
                return
            except Exception:
                logger.exception("Prediction failed for %s", ticker)
    finally:
        conn.close()


def _job_score_daily() -> None:
    """Score all due predictions and update bandit + calibration."""
    conn = get_conn()
    try:
        result = score_due(conn)
        logger.info(
            "Scoring complete: scored=%d skipped=%d already_scored=%d",
            result.scored,
            result.skipped,
            result.already_scored,
        )
    except Exception:
        logger.exception("Daily scoring failed")
    finally:
        conn.close()


def _job_reflect_weekly() -> None:
    """Run weekly reflection to update prediction rules."""
    conn = get_conn()
    try:
        result = reflect_weekly(conn)
        logger.info(
            "Reflection v%03d written (%s/%s), %d predictions reviewed",
            result.version,
            result.provider,
            result.model,
            result.prediction_count,
        )
    except CostCeilingError:
        logger.warning("Cost ceiling reached during weekly reflection")
    except Exception:
        logger.exception("Weekly reflection failed")
    finally:
        conn.close()


def _job_web_discovery() -> None:
    """Run a web-discovery cycle: search APIs + page fetch + LLM extraction."""
    conn = get_conn()
    try:
        result = run_discovery(conn)
        logger.info(
            "Discovery id=%d label=%s layer=%s queries=%d mentions=%d themes=%d cost=$%.4f",
            result.research_id,
            result.session_label,
            result.layer_focus,
            len(result.queries),
            len(result.extraction.mentions),
            len(result.extraction.themes),
            result.cost_usd,
        )
    except WebSearchUnavailable as exc:
        logger.warning(
            "Web discovery skipped: %s. Set TAVILY_API_KEY (or SERPER/BRAVE) in .env.",
            exc,
        )
    except CostCeilingError:
        logger.warning("Cost ceiling reached during web discovery, skipping")
    except Exception:
        logger.exception("Web discovery failed")
    finally:
        conn.close()


_RESEARCH_RETRY_DELAYS_SECS: tuple[int, ...] = (30, 90, 180)


def _job_pull_insiders() -> None:
    """Fetch fresh Form 4 insider filings for every active holding + watchlist ticker."""
    conn = get_conn()
    try:
        ticker_set: set[str] = set()
        for h in holdings.list_holdings(conn, active_only=True):
            ticker_set.add(h.ticker)
        for t in _get_active_tickers(conn):
            ticker_set.add(t)
        if not ticker_set:
            logger.info("No tickers to pull insiders for")
            return
        total = 0
        for ticker in sorted(ticker_set):
            try:
                inserted = persist_insiders(conn, ticker)
                total += inserted
            except Exception:
                logger.exception("Insider pull failed for %s", ticker)
        logger.info("Insider pull total inserted=%d", total)
    finally:
        conn.close()


def _job_health_check() -> None:
    """Run a per-holding health-check deep-dive; persist to research_reports."""
    conn = get_conn()
    try:
        active = holdings.list_holdings(conn, active_only=True)
        if not active:
            logger.info("Health-check skipped: no active holdings")
            return

        sections: list[str] = []
        last_research_id: int | None = None
        for h in active:
            try:
                report = generate_health_check(conn, holding=h)
                last_research_id = report.research_id
                sections.append(f"## {h.ticker}\n\n{report.body}")
            except CostCeilingError:
                logger.warning("Cost ceiling reached during health-check, stopping")
                break
            except Exception:
                logger.exception("Health-check failed for %s", h.ticker)

        if not sections:
            return

        # Per-ticker health-checks already live in research_reports; APK pulls them
        # via /channel/api/notes. No combined WeChat broadcast needed.
        _ = last_research_id
    finally:
        conn.close()


def _job_compute_anomalies() -> None:
    """Recompute price/volume anomalies right after the close-scoring job."""
    conn = get_conn()
    try:
        rows = anomaly.compute_daily_anomalies(conn)
        logger.info("Anomaly recompute flagged=%d rows", len(rows))
    except Exception:
        logger.exception("Anomaly recompute failed")
    finally:
        conn.close()


def _job_scan_intraday_holding_moves() -> None:
    """Live holding crash/spike alerts during the US session."""
    conn = get_conn()
    try:
        moves = alerts.scan_holdings_for_intraday_moves(conn)
        if moves:
            summary = ", ".join(f"{t}: {msg}" for t, msg in moves.items())
            logger.warning("Intraday holding move alerts fired: %s", summary)
    except Exception:
        logger.exception("Intraday holding move scan failed")
    finally:
        conn.close()


def _job_learn_from_feedback() -> None:
    """Classify recent inbound replies, queue follow-ups, auto-rewrite the prompt."""
    conn = get_conn()
    try:
        new_inbounds = read_feedback_entries(lookback_days=1)
        if not new_inbounds:
            logger.info("learn_from_feedback: no new inbound entries")
            return

        recorded_ids: list[int] = []
        for entry in new_inbounds:
            if conversation.has_entry(conn, entry.timestamp, entry.recipient):
                continue
            try:
                inbound_id = conversation.record_inbound(
                    entry.recipient, entry.text, conn,
                    created_at=entry.timestamp,
                )
            except Exception:
                logger.exception("conversation.record_inbound failed")
                continue
            recorded_ids.append(inbound_id)

            try:
                result = intent.classify(
                    entry.text, recipient=entry.recipient, conn=conn
                )
                conversation.set_intent(
                    conn, inbound_id, result.intent, result.confidence
                )
            except Exception:
                logger.exception("intent.classify failed for entry %s", inbound_id)
                continue

            # Treat "unknown" the same as "question": when the cheap classifier fails
                    # (LLM flake, JSON parse error, etc.) the boss still gets a reply
            # rather than silent stash. False positives just produce a polite answer.
            if result.intent in ("question", "unknown"):
                try:
                    reply_body = generate_reply(
                        conn, recipient=entry.recipient, boss_reply=entry.text
                    )
                    # Persist the reply as a research_reports row so the APK shows it
                    # via /channel/api/notes; cloud_sync pushes it to Render within 1 min.
                    topic_short = (entry.text or "").strip().replace("\n", " ")[:120]
                    cursor = conn.execute(
                        "INSERT INTO research_reports"
                        " (kind, topic, layer_focus, body, cost_usd, created_at)"
                        " VALUES ('reply', ?, NULL, ?, 0, ?)",
                        (topic_short, reply_body, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                    reply_research_id = int(cursor.lastrowid or 0) or None
                    logger.info(
                        "Reply note generated for %s: id=%s topic=%r len=%d",
                        entry.recipient, reply_research_id,
                        topic_short, len(reply_body),
                    )
                    rid = conversation.get_run_id(conn, inbound_id)
                    conversation.record_outbound(
                        entry.recipient, reply_body, conn,
                        run_id=rid, related_research_id=reply_research_id,
                    )
                except CostCeilingError:
                    logger.warning(
                        "learn_from_feedback: cost ceiling reached during reply"
                    )
                    return
                except Exception:
                    logger.exception(
                        "Reply generation failed for inbound %s", inbound_id
                    )
            elif result.intent == "instruction":
                try:
                    topic = result.suggested_topic or entry.text
                    action_queue.enqueue_actions(
                        conn, source_research_id=None, raw_items=[topic]
                    )
                except Exception:
                    logger.exception(
                        "action_queue.enqueue_actions failed for instruction %s",
                        inbound_id,
                    )

        # After all inbounds handled, fire prompt rewriter on any instruction-typed turns
        try:
            instruction_ids = conversation.recent_instruction_ids(conn, hours=12)
            if instruction_ids:
                proposals = prompt_rewriter.propose_rewrite(
                    instruction_ids, conn
                )
                for proposal in proposals:
                    prompt_rewriter.apply_rewrite(proposal, conn)
        except CostCeilingError:
            logger.warning("learn_from_feedback: cost ceiling during rewrite")
        except Exception:
            logger.exception("prompt_rewriter dispatch failed")
    finally:
        conn.close()


def _job_run_action_queue() -> None:
    """Drain the auto-queued action items so the next push can reference them."""
    conn = get_conn()
    try:
        completed = action_queue.run_pending(conn, max_items=4)
        logger.info("action_queue runner drained=%d", len(completed))
    except CostCeilingError:
        logger.warning("Cost ceiling reached during action_queue run, skipping")
    except Exception:
        logger.exception("action_queue runner failed")
    finally:
        conn.close()


def _job_pull_feedback() -> None:
    """Snapshot each recipient's WeChat chat so the operator can record their replies."""
    try:
        captures = pull_chat_screenshots()
        ok = sum(1 for c in captures if c.path)
        logger.info("Feedback inbox snapshots: %d ok / %d total", ok, len(captures))
    except Exception:
        logger.exception("pull-feedback job failed (delivery + research still proceed)")


def _job_research_push() -> None:
    """Generate the daily AI-supply-chain research note and push to WeChat recipients.

    Resilient to transient network failures: DNS / connection errors during the LLM
    call get retried with exponential backoff (30s, 90s, 180s) before giving up.
    """
    conn = get_conn()
    try:
        report = None
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0, *_RESEARCH_RETRY_DELAYS_SECS]):
            if delay:
                logger.info(
                    "Research push: retrying in %ds (attempt %d) after %s",
                    delay, attempt, type(last_exc).__name__,
                )
                time.sleep(delay)
            try:
                report = generate_daily_research(conn)
                break
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                httpx.ConnectError,
                httpx.ReadTimeout,
                ConnectionError,
                TimeoutError,
            ) as exc:
                last_exc = exc
                continue
            except CostCeilingError:
                logger.warning("Cost ceiling reached during research push, skipping")
                return
            except Exception:
                logger.exception("Research push failed (non-network error, no retry)")
                return

        if report is None:
            logger.error(
                "Research push: gave up after %d retries; last error: %s",
                len(_RESEARCH_RETRY_DELAYS_SECS), last_exc,
            )
            return

        logger.info(
            "Research generated id=%d layer=%s cost=$%.4f",
            report.research_id,
            report.layer_focus,
            report.cost_usd,
        )

        # Note already in research_reports; cloud_sync will push it to Render
        # and the APK polls /channel/api/notes. No WeChat GUI delivery needed.
    finally:
        conn.close()


def _job_email_daily_action_report() -> None:
    """Email the latest weekday daily research note to the operator."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, body, created_at FROM research_reports"
            " WHERE kind = 'daily' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            logger.warning("daily action email skipped: no daily research report found")
            return
        research_id, body, created_at = row
        subject = f"STOCK daily action report #{research_id} ({str(created_at)[:10]})"
        upload_link = _dashboard_upload_link(conn)
        email_body = str(body)
        warning = warning_dashboard.build_warning_dashboard(conn, days=7, limit=12)
        if warning.items:
            email_body = (
                f"{warning_dashboard.format_warning_dashboard(warning)}\n\n"
                "---\n"
                f"{email_body}"
            )
        if upload_link:
            email_body = (
                f"{email_body.rstrip()}\n\n"
                "---\n"
                "Upload holdings screenshot / submit feedback:\n"
                f"{upload_link}\n"
                "Caption suggestion: Update my holdings from this Robinhood screenshot\n"
            )
        result = emailer.send_email(subject=subject, body=email_body)
        if result.sent:
            logger.info("daily action email sent for research_id=%s", research_id)
        else:
            logger.warning(
                "daily action email not sent for research_id=%s: %s",
                research_id,
                result.detail,
            )
    finally:
        conn.close()


def _job_publish_warning_dashboard() -> None:
    """Publish changed warnings to boss app/Render and email high-risk changes."""
    conn = get_conn()
    try:
        result = warning_dashboard.publish_warning_dashboard(conn, days=7, limit=25)
        if not result.changed:
            return
        logger.info(
            "Warning dashboard published id=%s high=%d medium=%d",
            result.research_id,
            result.high_count,
            result.medium_count,
        )
        if result.high_count > 0:
            mail = emailer.send_email(
                subject=f"STOCK warning dashboard: {result.high_count} high-risk item(s)",
                body=result.body,
            )
            if not mail.sent:
                logger.warning("warning dashboard email not sent: %s", mail.detail)
    except Exception:
        logger.exception("Warning dashboard publish failed")
    finally:
        conn.close()


def _dashboard_upload_link(conn) -> str:
    """Return a Render dashboard link with the latest active recipient token."""
    settings = get_settings()
    base_url = (settings.render_sync_url or "").strip().rstrip("/")
    if not base_url:
        return ""

    preferred = ("richard", "yjz", "boss", "operator")
    row = None
    for recipient in preferred:
        row = conn.execute(
            "SELECT token FROM recipient_tokens"
            " WHERE revoked = 0 AND lower(recipient) = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (recipient,),
        ).fetchone()
        if row:
            break
    if row is None:
        row = conn.execute(
            "SELECT token FROM recipient_tokens"
            " WHERE revoked = 0 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return ""
    token_part = f"?token={row[0]}" if row else ""
    return f"{base_url}/channel/{token_part}"


def _job_backup_db() -> None:
    """F33: nightly SQLite online backup to data/backups/stock.db.<date>.bak."""
    try:
        result = backup.backup_now()
        logger.info(
            "DB backup ok: %s (%.1f MB)",
            result.backup_path, result.bytes / (1024 * 1024),
        )
    except FileNotFoundError as exc:
        logger.warning("DB backup skipped: %s", exc)
    except Exception:
        logger.exception("DB backup job failed")


TOPIC_QUEUE_PATH: str = "data/topic_queue.yaml"


def _pop_next_topic(sector: str) -> tuple[str, str, str] | None:
    """Pick the longest-untouched enabled topic for a sector from topic_queue.yaml.

    Updates last_run on the picked topic so the next run rotates through.
    Returns (sector, topic, phase) or None if no enabled topics for that sector.
    `phase` is the topic's early|emerging|mature tag (defaults to 'mature').
    """
    from pathlib import Path

    import yaml
    p = Path(TOPIC_QUEUE_PATH)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    topics = data.get("topics") or []

    candidates = [
        (i, t) for i, t in enumerate(topics)
        if t.get("enabled", True) and t.get("sector") == sector
    ]
    if not candidates:
        return None

    # Sort by last_run ASC (None first) so least-recent gets picked
    candidates.sort(key=lambda kv: kv[1].get("last_run") or "")
    idx, picked = candidates[0]
    topic = str(picked.get("topic", "")).strip()
    if not topic:
        return None
    phase = str(picked.get("phase") or "mature").strip().lower()

    picked["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topics[idx] = picked
    data["topics"] = topics
    p.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=200),
        encoding="utf-8",
    )
    return (sector, topic, phase)


COMPANY_DIVE_QUEUE_PATH: str = "data/company_dive_queue.yaml"


def _pop_next_company() -> str | None:
    """Pick the longest-untouched enabled company from company_dive_queue.yaml.

    Returns the ticker, or None if no enabled companies. Updates last_run
    in the YAML file so the next call rotates to the next company.
    """
    from pathlib import Path

    import yaml
    p = Path(COMPANY_DIVE_QUEUE_PATH)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    companies = data.get("companies") or []
    enabled = [(i, c) for i, c in enumerate(companies) if c.get("enabled", True)]
    if not enabled:
        return None
    # Sort by priority asc, then last_run asc (None first)
    enabled.sort(key=lambda kv: (
        kv[1].get("priority", 9), kv[1].get("last_run") or "",
    ))
    idx, picked = enabled[0]
    ticker = str(picked.get("ticker", "")).strip()
    if not ticker:
        return None
    picked["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    companies[idx] = picked
    data["companies"] = companies
    p.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=200),
        encoding="utf-8",
    )
    return ticker


def _job_company_dd_dive() -> None:
    """F44: every 4h30min, run dd_checklist on the next company in the queue.

    Pops 1 company per fire (~5-min wall clock). Boss directive 2026-05-07:
    iterate through the company queue at sub-session pace so each name gets
    a fresh DD checklist on schedule. Free via claude_cli.
    """
    from stock import analyst_skills
    ticker = _pop_next_company()
    if not ticker:
        logger.info("Company DD dive: no enabled companies in queue")
        return
    logger.info("Company DD dive starting: %s", ticker)
    conn = get_conn()
    try:
        report = analyst_skills.dd_checklist(ticker=ticker, conn=conn)
        if report.research_id:
            logger.info(
                "Company DD dive done: %s -> research_id=%s",
                ticker, report.research_id,
            )
    except Exception:
        logger.exception("Company DD dive failed for %s", ticker)
    finally:
        conn.close()


# Sector rotation for the weekly tech dive. Ordered list rotated by ISO week
# number so every tracked field gets periodic airtime -- including the buyer-side
# `ai_demand` sector and early-phase `space_tech`. (The old day-of-week map only
# ever fired on Sunday, so it always picked `energy` and the other sectors never
# ran via cron.)
TECH_DIVE_SECTORS: list[str] = [
    "information",
    "biopharma_ai",
    "energy",
    "ai_demand",
    "space_tech",
]


def _job_daily_tech_dive() -> None:
    """F43 weekly cron (Sun 04:30 UTC): rotate sector by ISO week, dive next topic.

    Picks the rotation-selected sector first, then falls back through the rest in
    order so an empty queue for one sector does not waste the week. The chosen
    topic's phase (early|emerging|mature) flows into the chokepoint scoring round.
    """
    week = datetime.now(timezone.utc).isocalendar().week
    n = len(TECH_DIVE_SECTORS)
    order = [TECH_DIVE_SECTORS[(week + i) % n] for i in range(n)]

    pick: tuple[str, str, str] | None = None
    for sector in order:
        pick = _pop_next_topic(sector)
        if pick:
            break
    if not pick:
        logger.info("Weekly tech dive: no enabled topics in any sector")
        return

    sector, topic, phase = pick
    logger.info(
        "Weekly tech dive starting: sector=%s phase=%s topic=%s",
        sector, phase, topic[:80],
    )
    conn = get_conn()
    try:
        dive = tech_dive.run_and_persist(
            topic=topic, sector=sector, conn=conn, language="zh", phase=phase,
        )
        if dive.rounds:
            logger.info(
                "Weekly tech dive done: research_id=%s rounds=%d composite=%s",
                dive.research_id, len(dive.rounds),
                dive.chokepoint.composite if dive.chokepoint else "n/a",
            )
    except Exception:
        logger.exception("Weekly tech dive failed (sector=%s)", sector)
    finally:
        conn.close()


def _job_post_close_snapshot() -> None:
    """F46: 20:05 UTC weekdays (4:05 PM ET) -- post-close volume + price snapshot.

    Re-fetches today's daily bar from yfinance (now FINAL post-close), then
    runs the conviction-list volume-vs-20d-avg scan from
    scripts/post_close_snapshot.py. Surfaces spikes + quiets. Boss directive:
    fresh real-time volume measured at the same time daily.
    """
    import subprocess
    import sys as _sys
    proc = subprocess.run(
        [_sys.executable, "scripts/post_close_snapshot.py"],
        capture_output=True, text=True, timeout=600,
        cwd=str(__file__).rsplit("src", 1)[0] if "src" in __file__ else ".",
    )
    if proc.returncode == 0:
        # Last line of stdout has 'Persisted research_id=N'
        last_lines = (proc.stdout or "").strip().splitlines()[-3:]
        logger.info("Post-close snapshot done: %s", " | ".join(last_lines))
    else:
        logger.error("Post-close snapshot failed (rc=%d): %s",
                     proc.returncode, (proc.stderr or "")[:300])


def _job_propose_stop_orders() -> None:
    """Compute desired SELL stop-limit orders for active holdings and PROPOSE them.

    Human-armed by design: writes data/desired_stop_orders.json and an alert note
    so the boss sees the proposed stops, but NEVER places an order. Placement is
    only done via the explicit `stock stops place --confirm` path. Runs after the
    post-close snapshot so stops use settled daily bars.
    """
    from stock import stop_orders
    conn = get_conn()
    try:
        orders = stop_orders.compute_desired_stops(conn)
        stop_orders.write_proposal(orders)
        if not orders:
            logger.info("Stop-order propose: no eligible active holdings")
            return
        block = stop_orders.format_proposal_block(orders)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO research_reports (kind, topic, body, created_at)"
            " VALUES ('alert', ?, ?, ?)",
            (f"⚠️ 止损挂单建议 / {len(orders)} proposed stop orders", block, now),
        )
        conn.commit()
        logger.info(
            "Stop-order propose: %d proposed (arm with `stock stops place --confirm`)",
            len(orders),
        )
    except Exception:
        logger.exception("Stop-order propose job failed")
    finally:
        conn.close()


def _job_weekly_entry_scan() -> None:
    """F45: Sunday 06:00 UTC scan -- which tracked names are in pullback zone?

    Pure price-table arithmetic, no LLM. Surfaces flagged names in a
    research_reports kind='entry_signals' row that the APK picks up.
    """
    conn = get_conn()
    try:
        rid, signals = entry_signals.run_and_persist(conn)
        in_zone = sum(1 for s in signals if s.classification == "IN_ZONE")
        logger.info(
            "Weekly entry scan: research_id=%s; %d scanned, %d in zone",
            rid, len(signals), in_zone,
        )
    except Exception:
        logger.exception("Weekly entry scan failed")
    finally:
        conn.close()


def _job_weekly_qa_dive() -> None:
    """F40: weekly autonomous Q&A deep-dive on the top-5 FWP candidates.

    Boss directive: "他主力盯住几只板块几个股票, 不断地做深入挖掘." Cron picks
    the highest-FWP names from discovery_candidates and runs F37's Q&A engine
    on each. 5 names × 5 rounds × ~700 tokens ~ $0.50-1.50 per weekly run --
    cheap insurance that the system stays digging into the same candidates
    week-over-week instead of forgetting what it found.

    Saturday 07:00 UTC = post-Friday-close, before the weekly reflect job.
    """
    from stock import discovery_engine, qa_deepdive
    conn = get_conn()
    try:
        candidates = discovery_engine.list_candidates(conn, status="candidate", limit=5)
        if not candidates:
            logger.info("Weekly QA: no candidates available -- skipping")
            return
        for c in candidates:
            try:
                seed = (
                    f"FWP score {c.fwp:.2f} (rank from latest discovery_engine run); "
                    f"signal components {dict((k, round(v, 2)) for k, v in c.components.items() if isinstance(v, (int, float)))}. "
                    f"Why is THIS the right time to dig deep, and what's the highest-conviction follow-up?"
                )
                dive = qa_deepdive.run_and_persist(
                    ticker=c.ticker, seed_thesis=seed, conn=conn, rounds=5,
                )
                logger.info(
                    "Weekly QA dive done: %s -> research_id=%s (%d rounds)",
                    c.ticker, dive.research_id, len(dive.rounds),
                )
            except CostCeilingError:
                logger.warning("Cost ceiling hit during weekly QA on %s; stopping", c.ticker)
                break
            except Exception:
                logger.exception("Weekly QA dive failed for %s", c.ticker)
                continue
    except Exception:
        logger.exception("Weekly QA orchestration failed")
    finally:
        conn.close()


def _job_measure_ai_loop() -> None:
    """F39: weekly measurement of the AI commercial-loop panel.

    Income statements only update quarterly, so a daily cron is wasteful;
    once a week is enough to catch new earnings prints across the panel.
    Runs Mondays at 06:30 UTC -- after the weekend, before the Monday
    morning research push.
    """
    conn = get_conn()
    try:
        measurements = ai_loop_monitor.measure_panel()
        n = ai_loop_monitor.persist(conn, measurements)
        status = ai_loop_monitor.overall_loop_status(measurements)
        flag_counts: dict[str, int] = {}
        for m in measurements:
            flag_counts[m.risk_flag] = flag_counts.get(m.risk_flag, 0) + 1
        logger.info(
            "AI loop measurement: %d new rows; status=%s; flags=%s",
            n, status, flag_counts,
        )
    except Exception:
        logger.exception("AI loop measurement job failed")
    finally:
        conn.close()


def _job_scan_smallcap_universe() -> None:
    """F38: nightly scan of the curated 3-sector small-cap universe.

    Runs at 22:30 UTC after FWP discovery_engine (23:00 UTC) -- wait, no,
    we need it BEFORE the discovery engine so the small-cap candidates
    can flow into the next morning's research note. Move to 22:15 UTC
    Mon-Fri; sits between the 21:30 score_daily and 23:00 discovery_engine.

    Pulls market cap + revenue trajectory via yfinance, computes the
    composite score, persists rows with score >= MIN_SCORE_TO_PERSIST.
    Per-ticker isolation; one failure doesn't crash the whole scan.
    """
    conn = get_conn()
    try:
        candidates = smallcap_scanner.scan_universe(conn)
        n_above_floor = sum(1 for c in candidates if c.score >= smallcap_scanner.MIN_SCORE_TO_PERSIST)
        smallcap_scanner.persist(conn, candidates)
        logger.info(
            "Smallcap scan: %d scanned, %d above noise floor, %d sectors",
            len(candidates), n_above_floor,
            len({c.sector for c in candidates}),
        )
    except Exception:
        logger.exception("Smallcap scan job failed")
    finally:
        conn.close()


def _job_scan_unusual_options() -> None:
    """F36: scan watchlist + holdings tickers for unusual options activity.

    Runs once per session at 21:55 UTC -- a few minutes after the close so
    yfinance has the day's final volume + open interest snapshot. Persists
    UOA hits to option_anomalies; an extreme hit (vol/OI >= 20 OR volume
    >= 10000) on a holding triggers a kind='alert' research_reports row
    so the boss sees it in the next push.
    """
    conn = get_conn()
    try:
        tickers = sorted(
            {
                *_get_active_tickers(conn),
                *{h.ticker for h in holdings.list_holdings(conn, active_only=True)},
                "FUTU",
                "TIGR",
            }
        )
        total_hits = 0
        total_ratios = 0
        for ticker in tickers:
            try:
                ratio = options_module.scan_ratio_snapshot(conn, ticker)
                if ratio is not None:
                    total_ratios += 1
                hits = options_module.scan_ticker(conn, ticker)
            except Exception:  # noqa: BLE001 -- per-ticker isolation
                logger.debug("UOA scan failed for %s", ticker, exc_info=True)
                continue
            total_hits += len(hits)
            extreme = [h for h in hits if h.vol_oi_ratio >= 20 or h.volume >= 10000]
            if extreme and ticker.upper() in {t.upper() for t in {h.ticker for h in holdings.list_holdings(conn, active_only=True)}}:
                _write_uoa_alert(conn, ticker, extreme)
        logger.info(
            "UOA scan: %d tickers, %d total hits, %d ratio snapshots",
            len(tickers), total_hits, total_ratios,
        )
    except Exception:
        logger.exception("UOA scan job failed")
    finally:
        conn.close()


def _write_uoa_alert(conn: sqlite3.Connection, ticker: str, hits: list) -> None:
    """Persist an alert-kind research_reports row for extreme UOA on a holding."""
    summary_lines = [f"# 异常期权流入 {ticker}", ""]
    for h in hits[:3]:
        summary_lines.append(
            f"- {h.option_type.upper()} ${h.strike:.0f} {h.expiry}: "
            f"vol={h.volume:,} OI={h.open_interest:,} ({h.vol_oi_ratio:.1f}x) "
            f"-- {h.flag_reason}"
        )
    body = "\n".join(summary_lines)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO research_reports (kind, topic, body, created_at)"
        " VALUES ('alert', ?, ?, ?)",
        (f"{ticker} 异常期权", body, now),
    )
    conn.commit()


def _job_verify_tracked_events() -> None:
    """F26: nightly verification of pending tracked events against post-window news.

    Runs at 21:50 UTC Mon-Fri after the score + thesis_verify + grade pipeline so
    fresh news ingest is already in. Drains up to 30 events per run; cost-ceiling
    skip + per-event exception isolation.
    """
    conn = get_conn()
    try:
        graded = events.verify_due_events(conn, max_items=30)
        if graded:
            counts: dict[str, int] = {}
            for ev in graded:
                counts[ev.status] = counts.get(ev.status, 0) + 1
            counts_str = ", ".join(f"{k}={v}" for k, v in counts.items())
            logger.info(
                "Tracked events verified: %d total (%s)", len(graded), counts_str,
            )
        else:
            logger.info("Tracked events: no pending events due for verification")
    except CostCeilingError:
        logger.warning("Cost ceiling reached during event verification, skipping")
    except Exception:
        logger.exception("Event verification job failed")
    finally:
        conn.close()


def _job_run_discovery_engine() -> None:
    """F19: forward-looking candidate scoring + auto-promote.

    Runs daily at 23:00 UTC (07:00 Beijing) -- after the close-scoring + grading
    cycle so insider/news tables are fresh, before the next morning's research
    push so promoted candidates are included in the watchlist block.
    """
    conn = get_conn()
    try:
        result = discovery_engine.run_discovery_engine(conn, auto_promote=True)
        logger.info(
            "Discovery engine: universe=%d scored=%d new=%d updated=%d"
            " promoted=%s apewisdom_ok=%s",
            result.universe_size, result.scored,
            result.new_candidates, result.updated_candidates,
            ",".join(result.promoted_tickers) if result.promoted_tickers else "none",
            result.apewisdom_hit,
        )
        for cs in result.top_candidates[:5]:
            logger.info(
                "  candidate %s FWP=%.3f gate=%s",
                cs.ticker, cs.fwp, cs.qap_gate,
            )
    except Exception:
        logger.exception("Discovery engine job failed")
    finally:
        conn.close()


def _job_verify_theses() -> None:
    """Grade every ungraded thesis whose underlying prediction is now scored.

    Runs ~5 min after _job_score_daily so newly-graded predictions have their
    claims verified before _job_grade_and_reply pulls thesis stats into the
    grading note. Best-effort: cost-ceiling skip + per-thesis exception isolation.
    """
    conn = get_conn()
    try:
        graded = thesis.verify_due_theses(conn, max_items=30)
        logger.info("Theses verified: %d graded this tick", len(graded))
    except CostCeilingError:
        logger.warning("Cost ceiling reached during thesis verification, skipping")
    except Exception:
        logger.exception("Thesis verification job failed")
    finally:
        conn.close()


def _job_grade_and_reply() -> None:
    """Refresh prices, score yesterday's predictions, generate a grading note + follow-ups.

    Runs after _job_score_daily so any newly-due predictions are graded first.
    The grading note is persisted as a research_reports row of kind='grading';
    cloud_sync pushes it to Render and the APK polls /channel/api/notes. Follow-up
    topics are auto-queued so the next research push references the deep-dives.
    """
    conn = get_conn()
    try:
        note = grading.generate_grading_note(conn)
        logger.info(
            "Grading note id=%d total=%d hits=%d hit_rate=%.2f"
            " refreshed=%d follow_ups=%d rewrites=%d/%d cost=$%.4f",
            note.research_id,
            note.stats.total,
            note.stats.hits,
            note.stats.hit_rate,
            len(note.refreshed.tickers),
            note.follow_ups_queued,
            note.rewrites_applied,
            note.rewrites_staged,
            note.cost_usd,
        )
    except CostCeilingError:
        logger.warning("Cost ceiling reached during grading note, skipping")
    except Exception:
        logger.exception("Grade-and-reply job failed")
    finally:
        conn.close()


def _job_daily_self_review() -> None:
    """Compile pipeline/daily_review_YYYY-MM-DD.md and route to configured backend."""
    conn = get_conn()
    try:
        result = self_review.run_daily_review(conn)
        if result.path:
            logger.info("Self-review packet: %s", result.path)
    except Exception:
        logger.exception("Daily self-review failed")
    finally:
        conn.close()


def _job_sync_to_render() -> None:
    """Push local state to the Render free-tier proxy and pull boss replies.

    Acts as a 5-min keepalive on the Render free instance so it doesn't sleep,
    and bridges boss replies typed into the dashboard back into the F13 feedback
    pipeline.
    """
    settings = get_settings()
    if not (settings.render_sync_url or "").strip():
        return  # not configured -- silently skip
    conn = get_conn()
    try:
        result = run_local_sync(conn)
        if result.error:
            logger.warning("Render sync error: %s", result.error)
        elif (
            result.notes_pushed
            or result.tokens_pushed
            or result.replies_pulled
        ):
            # Only surface a sync log line when something actually moved -- empty
            # "notes=0 tokens=0 replies=0" ticks are silent to keep the log clean.
            logger.info(
                "Render sync: notes=%d tokens=%d replies=%d",
                result.notes_pushed, result.tokens_pushed, result.replies_pulled,
            )
    except Exception:
        logger.exception("Render sync raised unexpectedly")
    finally:
        conn.close()


def _job_import_broker_snapshot() -> None:
    """Import filled broker positions from the local Robinhood snapshot bridge."""
    conn = get_conn()
    try:
        result = broker_sync.import_snapshot_file(conn)
        if result.missing:
            return
        if result.upserted or result.deactivated:
            logger.info(
                "Broker snapshot import: upserted=%d deactivated=%d skipped_empty=%d account=%s",
                result.upserted,
                result.deactivated,
                result.skipped_empty,
                result.account_number or "unknown",
            )
    except Exception:
        logger.exception("Broker snapshot import failed")
    finally:
        conn.close()


def _job_pull_broker_positions() -> None:
    """Pull LIVE Robinhood positions via codex/RH-MCP, import them, refresh prices.

    Read-only (get_equity_positions). This is what keeps the holdings table -- and
    therefore the warning dashboard -- in sync with the real account instead of a
    stale data/holdings.yaml. After import it refreshes daily bars for the held
    tickers so P&L and stop-distance reflect the latest stock data. The warning
    dashboard (every 15 min) then re-evaluates on this fresh data.
    """
    from stock.ingest import fetch_prices
    conn = get_conn()
    try:
        try:
            pull = broker_sync.pull_positions_via_codex()
        except broker_sync.BrokerPullError as exc:
            logger.warning("Broker positions pull skipped: %s", exc)
            return
        imp = broker_sync.import_snapshot_file(conn)
        # Refresh latest daily bars for held tickers so the warning is current.
        refreshed = 0
        for h in holdings.list_holdings(conn, active_only=True):
            try:
                fetch_prices(h.ticker, conn)
                refreshed += 1
            except Exception as exc:  # noqa: BLE001 -- isolate per-ticker failures
                logger.warning("price refresh failed for %s: %s", h.ticker, exc)
        logger.info(
            "Broker positions pull: %d live positions, upserted=%d deactivated=%d,"
            " refreshed prices for %d holdings",
            pull.get("count", 0), imp.upserted, imp.deactivated, refreshed,
        )
    except Exception:
        logger.exception("Broker positions pull job failed")
    finally:
        conn.close()


def create_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler instance with all pipeline jobs.

    In `STOCK_MODE=cloud_proxy` (Render-side passive mode) the scheduler is empty:
    Render only serves /channel/* and /sync/* endpoints, the local laptop drives
    everything else.
    """
    scheduler = BlockingScheduler(timezone="UTC")

    settings = get_settings()
    if (settings.stock_mode or "").strip().lower() == "cloud_proxy":
        logger.info(
            "STOCK_MODE=cloud_proxy -- scheduler is a no-op; FastAPI serves /channel/* and /sync/* only"
        )
        return scheduler

    # Ingest news/prices/features TWICE DAILY -- right before each research
    # push (02:00 UTC for the 02:30 morning push, 14:00 UTC for the 14:30
    # evening push). Boss directive 2026-05-08: 15-min cadence was overkill
    # because the boss-readable artifacts only fire 2x/day; running ingest
    # 30+ times per day was just spawning subprocess flashes for no gain.
    scheduler.add_job(
        _job_ingest_and_extract,
        CronTrigger(hour="2,14", minute=0, day_of_week="mon-fri", timezone="UTC"),
        id="ingest_and_extract",
        name="Ingest news/prices/features (2x weekdays, pre-push)",
    )

    # Predictions twice daily, between ingest and research push, weekdays.
    # Was: every hour during market hours (8 fires/day).
    # Now: 2 fires/day matching the research-push cadence.
    scheduler.add_job(
        _job_run_predictions,
        CronTrigger(hour="2,14", minute=15, day_of_week="mon-fri", timezone="UTC"),
        id="run_predictions",
        name="Run predictions on watchlist (2x daily)",
    )

    # Score end-of-day at 21:30 UTC (Mon-Fri)
    scheduler.add_job(
        _job_score_daily,
        CronTrigger(
            hour=SCORE_HOUR,
            minute=SCORE_MINUTE,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="score_daily",
        name="Score due predictions",
    )

    # Weekly reflection: Saturday 06:00 UTC
    scheduler.add_job(
        _job_reflect_weekly,
        CronTrigger(
            hour=REFLECT_HOUR,
            minute=0,
            day_of_week=REFLECT_DAY,
            timezone="UTC",
        ),
        id="reflect_weekly",
        name="Weekly reflection",
    )

    # Web discovery (search + fetch + LLM extraction) before each research push
    scheduler.add_job(
        _job_web_discovery,
        CronTrigger(
            hour=DISCOVERY_MORNING_HOUR,
            minute=DISCOVERY_MORNING_MINUTE,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="web_discovery_morning",
        name="Morning web discovery",
    )
    scheduler.add_job(
        _job_web_discovery,
        CronTrigger(
            hour=DISCOVERY_EVENING_HOUR,
            minute=DISCOVERY_EVENING_MINUTE,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="web_discovery_evening",
        name="Evening web discovery",
    )

    # WeChat feedback-pull crons removed 2026-05-04: the boss now talks to the
    # system via the dashboard / APK (POST /channel/api/reply). The old crons
    # used pyautogui to open WeChat -> click each recipient -> screenshot, and
    # the user reported it as "Claude controlling my laptop trying to message
    # 杨建中". The wechat_inbox module is kept on disk (CLI `stock pull-feedback`
    # still works for manual one-off captures) but nothing fires on a schedule.

    # Daily anomaly recompute right after close-scoring
    scheduler.add_job(
        _job_compute_anomalies,
        CronTrigger(
            hour=SCORE_HOUR,
            minute=SCORE_MINUTE + 5,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="anomaly_compute",
        name="Daily price/volume anomaly computation",
    )

    # Live holding crash/spike alerts during the US cash session. This catches
    # active-holding moves before the post-close anomaly job has a settled bar.
    scheduler.add_job(
        _job_scan_intraday_holding_moves,
        CronTrigger(hour="13-20", minute="*/15", day_of_week="mon-fri", timezone="UTC"),
        id="intraday_holding_move_alerts",
        name="Intraday holding crash/spike alerts",
    )

    # Weekly insider Form 4 pull on Sundays 05:00 UTC
    scheduler.add_job(
        _job_pull_insiders,
        CronTrigger(hour=5, minute=0, day_of_week="sun", timezone="UTC"),
        id="insiders_pull",
        name="Weekly EDGAR Form 4 pull",
    )

    # Per-holding health-check deep-dive every Saturday 07:00 UTC
    scheduler.add_job(
        _job_health_check,
        CronTrigger(hour=7, minute=0, day_of_week="sat", timezone="UTC"),
        id="health_check_weekly",
        name="Per-holding weekly health-check deep-dive",
    )

    # Learn-from-feedback fires every 5 min so boss replies are processed within
    # minutes (down from up to 12h originally). No-ops when no new inbound entries;
    # prompt_rewriter has a 24h-per-file rate limit so it can't spam updates.
    scheduler.add_job(
        _job_learn_from_feedback,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="learn_from_feedback",
        name="Classify replies, queue follow-ups, auto-rewrite prompt",
    )

    # Drain the auto-queued action items 90 minutes before each push so the
    # resulting deep-dives can be referenced as "前一轮跟进" in the next note.
    scheduler.add_job(
        _job_run_action_queue,
        CronTrigger(
            hour=f"{(RESEARCH_MORNING_HOUR - 2) % 24},{(RESEARCH_EVENING_HOUR - 2) % 24}",
            minute=0,
            timezone="UTC",
        ),
        id="action_queue_runner",
        name="Run pending auto-queued action items",
    )

    # Twice-daily AI-supply-chain research push on weekdays. Weekend market scans
    # are intentionally off; weekly maintenance/deep-dive jobs still run.
    scheduler.add_job(
        _job_research_push,
        CronTrigger(
            hour=RESEARCH_MORNING_HOUR,
            minute=RESEARCH_MORNING_MINUTE,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="research_push_morning",
        name="Morning research + WeChat push",
    )
    scheduler.add_job(
        _job_research_push,
        CronTrigger(
            hour=RESEARCH_EVENING_HOUR,
            minute=RESEARCH_EVENING_MINUTE,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="research_push_evening",
        name="Evening research + WeChat push",
    )

    scheduler.add_job(
        _job_email_daily_action_report,
        CronTrigger(hour=14, minute=45, day_of_week="mon-fri", timezone="UTC"),
        id="daily_action_email",
        name="Email latest daily action report",
    )

    # Sync every 5 seconds so dashboard replies are pulled + processed near-
    # instantly (a human can't tell it from real-time). The sync is a cheap HTTP
    # round-trip (no LLM cost on an empty poll; LLM only fires when a reply is
    # actually pulled), and it doubles as keepalive that stops the Render free
    # tier from spinning down (cold-start ~30s otherwise). max_instances=1 +
    # coalesce skip/merge ticks while a previous sync is still mid-call, so a slow
    # Render round-trip can't pile up. No-op when render_sync_url is unset.
    scheduler.add_job(
        _job_sync_to_render,
        IntervalTrigger(seconds=5, timezone="UTC"),
        id="sync_to_render",
        name="Push state to Render free tier + pull boss replies",
        max_instances=1,
        coalesce=True,
    )

    # Publish changed warning dashboards as research_reports so the Boss app,
    # Render sync, and email all see the same risk surface.
    scheduler.add_job(
        _job_publish_warning_dashboard,
        CronTrigger(minute="*/15", timezone="UTC"),
        id="warning_dashboard_publish",
        name="Publish changed warning dashboard to app/email",
    )

    # Robinhood MCP bridge: Codex/RH MCP writes filled positions to
    # data/robinhood_positions_snapshot.json; the orchestrator imports it into
    # holdings every 5 minutes. Queued orders are not treated as holdings.
    scheduler.add_job(
        _job_import_broker_snapshot,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="broker_snapshot_import",
        name="Import filled Robinhood positions snapshot into holdings",
    )

    # Pull LIVE Robinhood positions via codex/RH-MCP every 30 min during the US
    # session, then refresh held-ticker prices, so the holdings table + warning
    # dashboard reflect the real account and latest stock data (not a stale
    # holdings.yaml). Read-only; never places orders.
    scheduler.add_job(
        _job_pull_broker_positions,
        CronTrigger(minute="*/30", hour="12-21", day_of_week="mon-fri", timezone="UTC"),
        id="broker_positions_pull",
        name="Pull live Robinhood positions + refresh holding prices",
    )

    # F26: tracked-event verification at SCORE_HOUR:SCORE_MINUTE+20 (Mon-Fri).
    # Runs after score + thesis_verify + grade pipeline so fresh news ingest is
    # already in.
    scheduler.add_job(
        _job_verify_tracked_events,
        CronTrigger(
            hour=SCORE_HOUR,
            minute=SCORE_MINUTE + 20,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="verify_tracked_events",
        name="F26 nightly tracked-event verification",
    )

    # F33: nightly SQLite backup at 23:30 UTC (between discovery_engine at
    # 23:00 and the 02:30 morning research push). Online backup is safe under
    # concurrent writes; retains the last 7 daily snapshots.
    scheduler.add_job(
        _job_backup_db,
        CronTrigger(hour=23, minute=30, timezone="UTC"),
        id="backup_db",
        name="F33 nightly SQLite online backup",
    )

    # F36: unusual-options-activity scan, 21:55 UTC Mon-Fri (a few minutes
    # after the close). Persists to option_anomalies; extreme hits on a
    # holding fire a kind='alert' research_reports row for the next push.
    scheduler.add_job(
        _job_scan_unusual_options,
        CronTrigger(hour=21, minute=55, day_of_week="mon-fri", timezone="UTC"),
        id="uoa_scan",
        name="F36 unusual options activity scan",
    )

    # F38: small-cap "find before it explodes" scan, 22:15 UTC Mon-Fri.
    # Runs between score_daily (21:30) and discovery_engine (23:00) so the
    # smallcap_candidates table is fresh for the next morning's research push.
    scheduler.add_job(
        _job_scan_smallcap_universe,
        CronTrigger(hour=22, minute=15, day_of_week="mon-fri", timezone="UTC"),
        id="smallcap_scan",
        name="F38 three-sector smallcap forward-discovery scan",
    )

    # F39: AI commercial-loop measurement, weekly Monday 06:30 UTC. Income
    # statements only update quarterly so a daily cron would burn yfinance
    # quota for nothing; once-weekly catches new earnings across the panel.
    scheduler.add_job(
        _job_measure_ai_loop,
        CronTrigger(day_of_week="mon", hour=6, minute=30, timezone="UTC"),
        id="ai_loop_measure",
        name="F39 weekly AI commercial-loop closure-risk measurement",
    )

    # F40: weekly autonomous Q&A deep-dive on the top-5 FWP candidates.
    # Saturday 07:00 UTC, after the Friday discovery_engine + before the
    # weekly reflect job. Cost: 5 names x 5 rounds x ~700 tokens.
    scheduler.add_job(
        _job_weekly_qa_dive,
        CronTrigger(day_of_week="sat", hour=7, minute=0, timezone="UTC"),
        id="weekly_qa_dive",
        name="F40 weekly Q&A deep-dive on top-FWP candidates",
    )

    # F43 weekly tech dive. This used to be a daily 04:30 UTC cron, then was
    # disabled on 2026-05-07 after the initial topic queue was covered. Re-enabled
    # weekly on 2026-05-25 so the tech-trend queue keeps moving without producing
    # duplicate daily artifacts.
    scheduler.add_job(
        _job_daily_tech_dive,
        CronTrigger(day_of_week="sun", hour=4, minute=30, timezone="UTC"),
        id="weekly_tech_dive",
        name="F43 weekly tech-trend deep-dive (sector-rotated)",
    )

    # F44 company DD dive: weekly Wednesday 09:00 UTC. Boss directive
    # 2026-05-08: previous 5x/day cadence created too many duplicate
    # artifacts; weekly is enough to keep one company per week refreshed.
    # The DD output now appends to pipeline/dd/<TICKER>.md so each
    # company file accumulates history across runs.
    scheduler.add_job(
        _job_company_dd_dive,
        CronTrigger(day_of_week="wed", hour=9, minute=15, timezone="UTC"),
        id="company_dd_dive",
        name="F44 weekly company DD checklist (queue-rotated)",
    )

    # F45 weekly entry-signal scan: Sunday 06:00 UTC. Scans all conviction +
    # dive-queue tickers, flags those in the recommended pullback zone. Free
    # (price-table arithmetic only, no LLM). Surfaced on APK as kind=
    # 'entry_signals'. Boss directive 2026-05-08: "flag good time to enter".
    scheduler.add_job(
        _job_weekly_entry_scan,
        CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="UTC"),
        id="weekly_entry_scan",
        name="F45 weekly entry-zone scan (conviction + DD queue)",
    )

    # F46 post-close volume snapshot: 20:05 UTC weekdays (4:05 PM ET, 5 min
    # after US close so yfinance has the FINAL settled bar). Boss directive
    # 2026-05-08 EOD: "make sure when you check on volume you check real-time
    # data ... or whenever we need volume we check at 4:01 PM Eastern Time."
    # Refreshes today's bar then flags spikes (>=2x avg) + quiets (<=0.5x avg).
    scheduler.add_job(
        _job_post_close_snapshot,
        CronTrigger(hour=20, minute=5, day_of_week="mon-fri", timezone="UTC"),
        id="post_close_snapshot",
        name="F46 post-close volume + price snapshot (4:05 PM ET)",
    )

    # Human-armed stop-loss: compute + PROPOSE sell stop-limit orders after the
    # post-close snapshot (settled bars). Writes the proposal + an alert note;
    # never places. Operator arms placement with `stock stops place --confirm`.
    scheduler.add_job(
        _job_propose_stop_orders,
        CronTrigger(hour=20, minute=10, day_of_week="mon-fri", timezone="UTC"),
        id="stop_order_propose",
        name="Propose human-armed stop-limit orders for active holdings",
    )

    # F19: forward-discovery engine daily at 23:00 UTC (07:00 Beijing). Runs
    # after the close-scoring + grading cycle so insider/news tables are fresh,
    # before the next morning's research push so promoted candidates appear in
    # the watchlist block.
    scheduler.add_job(
        _job_run_discovery_engine,
        CronTrigger(
            hour=23,
            minute=0,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="discovery_engine",
        name="F19 forward-looking candidate scoring + auto-promote",
    )

    # F16: thesis verification at SCORE_HOUR:SCORE_MINUTE+10 (Mon-Fri). Runs
    # after score_daily so newly-graded predictions have their claims verified
    # before grade_and_reply pulls thesis stats into the grading note.
    scheduler.add_job(
        _job_verify_theses,
        CronTrigger(
            hour=SCORE_HOUR,
            minute=SCORE_MINUTE + 10,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="thesis_verify",
        name="Verify scored theses against post-window evidence",
    )

    # Daily grade-and-reply at 21:45 UTC (Mon-Fri), 15 min after score_daily.
    # Refreshes prices, grades yesterday's predictions, writes a research_reports
    # row of kind='grading' so the APK shows it, and auto-queues follow-up topics
    # that feed into the next research push (closes the F11 improvement loop).
    scheduler.add_job(
        _job_grade_and_reply,
        CronTrigger(
            hour=SCORE_HOUR,
            minute=SCORE_MINUTE + 15,
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="grade_and_reply",
        name="Daily grade-and-reply note + follow-ups",
    )

    # Daily self-review packet at 06:00 UTC (after evening push + learn cycle complete).
    # Writes pipeline/daily_review_YYYY-MM-DD.md and routes improvement work
    # through Codex CLI when enabled.
    scheduler.add_job(
        _job_daily_self_review,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="daily_self_review",
        name="Daily self-review packet + optional Codex proposals",
    )

    return scheduler


def get_schedule_info(scheduler: BlockingScheduler) -> ScheduleInfo:
    """Build a summary of next-run times for all scheduled jobs."""
    # Compute next fire time from each job's trigger; pre-start jobs have no next_run_time
    now = datetime.now(timezone.utc)
    jobs: list[dict[str, str]] = []
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        if next_run is None:
            next_run = job.trigger.get_next_fire_time(None, now)
        jobs.append({
            "name": job.name or job.id,
            "next_run": next_run.isoformat() if next_run else "paused",
        })
    return ScheduleInfo(jobs=jobs)


def _configure_logging() -> Path:
    """Set up stderr + daily-rotated file logging. Return the active log file path."""
    from logging.handlers import TimedRotatingFileHandler

    # Ensure the log directory exists alongside the existing pipeline/ outputs
    log_dir = Path("pipeline/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "orchestrator.log"

    # Format includes ISO-style timestamp, logger name, level, message
    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    # Reset root handlers so this is idempotent across restarts in same process
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    # Stderr stays so the live PowerShell window keeps showing logs
    stderr_h = logging.StreamHandler()
    stderr_h.setFormatter(formatter)
    root.addHandler(stderr_h)

    # File: daily rotation at midnight, keep 14 days of history; greppable
    file_h = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=False,
    )
    file_h.setFormatter(formatter)
    root.addHandler(file_h)

    # Silence per-request httpx 200 OK noise and per-tick scheduler chatter.
    # Both still emit warnings/errors -- only the per-tick INFO lines are dropped.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)

    return log_path


def run_orchestrator() -> None:
    """Start the orchestrator and block until interrupted."""
    # Wire stderr + rotating file logging
    log_path = _configure_logging()
    logger.info("Log file: %s (daily rotation, 14 days kept)", log_path)

    # Verify DB is reachable and log watchlist state
    conn = get_conn()
    tickers = _get_active_tickers(conn)
    try:
        synced = holdings.sync_from_yaml(conn)
        if synced:
            logger.info("Holdings sync from YAML: %d rows upserted", synced)
    except Exception:
        logger.exception("Holdings YAML sync failed (non-fatal)")
    conn.close()
    logger.info(
        "Watchlist: %d tickers (%s)",
        len(tickers),
        ", ".join(tickers) if tickers else "none",
    )

    # Build scheduler and log the schedule
    scheduler = create_scheduler()
    info = get_schedule_info(scheduler)
    for entry in info.jobs:
        logger.info("Scheduled: %s -> %s", entry["name"], entry["next_run"])

    # Block until Ctrl+C or system shutdown
    logger.info("Orchestrator running (%d jobs). Press Ctrl+C to stop.", len(info.jobs))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Orchestrator stopped")
