"""stock.orchestrator -- scheduled job runner for the prediction pipeline."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

import time

import httpx
import openai

from stock import action_queue, alerts, anomaly, conversation, discovery_engine, events, grading, holdings, intent, prompt_rewriter, self_review, thesis
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
from stock.wechat import broadcast, send_message
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
            # (MiniMax flake, JSON parse error, etc.) the boss still gets a reply
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
            " refreshed=%d follow_ups=%d cost=$%.4f",
            note.research_id,
            note.stats.total,
            note.stats.hits,
            note.stats.hit_rate,
            len(note.refreshed.tickers),
            note.follow_ups_queued,
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

    # News + prices + features every 15 min during market hours (Mon-Fri)
    scheduler.add_job(
        _job_ingest_and_extract,
        CronTrigger(
            minute="*/15",
            hour=f"{MARKET_HOURS_START}-{MARKET_HOURS_END}",
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="ingest_and_extract",
        name="Ingest news/prices and extract features",
    )

    # Predictions every 60 min during market hours (Mon-Fri)
    scheduler.add_job(
        _job_run_predictions,
        CronTrigger(
            minute=0,
            hour=f"{MARKET_HOURS_START}-{MARKET_HOURS_END}",
            day_of_week="mon-fri",
            timezone="UTC",
        ),
        id="run_predictions",
        name="Run predictions on watchlist",
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

    # Twice-daily AI-supply-chain research push (every day, including weekends)
    scheduler.add_job(
        _job_research_push,
        CronTrigger(
            hour=RESEARCH_MORNING_HOUR,
            minute=RESEARCH_MORNING_MINUTE,
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
            timezone="UTC",
        ),
        id="research_push_evening",
        name="Evening research + WeChat push",
    )

    # Sync every 5 seconds to match the APK burst-poll cadence. APScheduler skips
    # overlapping ticks while F13 is mid-call. Doubles as keepalive on Render free
    # tier. No-op when render_sync_url is unset.
    scheduler.add_job(
        _job_sync_to_render,
        CronTrigger(second="*/5", timezone="UTC"),
        id="sync_to_render",
        name="Push state to Render free tier + pull boss replies",
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
    # Writes pipeline/daily_review_YYYY-MM-DD.md; if SELF_REVIEW_BACKEND=minimax|both,
    # also auto-calls MiniMax for ranked code-level proposals.
    scheduler.add_job(
        _job_daily_self_review,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="daily_self_review",
        name="Daily self-review packet + optional MiniMax proposals",
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
