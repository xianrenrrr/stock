"""stock.cli -- typer CLI for the stock prediction pipeline."""
from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Annotated

import typer

from stock import action_queue, anomaly, holdings
from stock.db import get_conn
from stock.discover import (
    get_latest_discovery,
    run_discovery,
)
from stock.ingest import fetch_news, fetch_prices
from stock.learn import reflect_weekly
from stock.predict import predict_ticker
from stock.research import (
    generate_daily_research,
    generate_deep_dive,
    get_latest_report,
)
from stock.score import build_report, format_report, score_due
from stock.supply_chain import (
    chain_summary_for_log,
    format_layer_players,
    list_layer_names,
    load_chain,
)
from stock.websearch import WebSearchUnavailable
from stock.wechat import (
    broadcast,
    list_pending_outbox,
    load_recipients,
    mark_outbox_delivered,
    send_message,
    trigger_openclaw_delivery,
)
from stock.wechat_gui import deliver_pending as gui_deliver_pending
from stock.wechat_inbox import (
    append_feedback,
    pull_chat_screenshots,
    read_feedback_entries,
)

app = typer.Typer(name="stock", help="Stock prediction pipeline CLI.")
ingest_app = typer.Typer(help="Ingest news and price data.")
app.add_typer(ingest_app, name="ingest")
queue_app = typer.Typer(help="Inspect and run the auto-queued action items.")
app.add_typer(queue_app, name="action-queue")
holding_app = typer.Typer(help="Manage tracked portfolio holdings.")
app.add_typer(holding_app, name="holding")
channel_app = typer.Typer(help="Manage per-recipient dashboard tokens (channel.py).")
app.add_typer(channel_app, name="channel-token")


@channel_app.command("issue")
def channel_token_issue_cmd(
    recipient: Annotated[str, typer.Argument(help="Recipient alias (yjz / 杨建中 / richard)")],
) -> None:
    """Issue a new dashboard bearer token for a recipient."""
    try:
        from stock import channel as _channel

        conn = get_conn()
        token = _channel.mint_token(conn, recipient)
        typer.echo(f"Issued token for {recipient}:")
        typer.echo(f"  {token}")
        typer.echo()
        typer.echo("Send this URL to the recipient (token will be auto-stored in their browser):")
        typer.echo(f"  https://<your-render-url>/channel/?token={token}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@channel_app.command("list")
def channel_token_list_cmd(
    include_revoked: Annotated[
        bool, typer.Option("--all", help="Include revoked tokens")
    ] = False,
) -> None:
    """List all dashboard tokens."""
    try:
        from stock import channel as _channel

        conn = get_conn()
        rows = _channel.list_tokens(conn, include_revoked=include_revoked)
        if not rows:
            typer.echo("No tokens.")
            return
        typer.echo(f"{'recipient':<20}{'last_seen':<22}{'revoked':<8}{'token':<40}")
        for r in rows:
            typer.echo(
                f"{str(r['recipient']):<20}"
                f"{str(r.get('last_seen_at') or '-'):<22}"
                f"{str(r['revoked']):<8}"
                f"{str(r['token'])[:32]}..."
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@channel_app.command("revoke")
def channel_token_revoke_cmd(
    token: Annotated[str, typer.Argument(help="Full token value to revoke")],
) -> None:
    """Revoke a dashboard token (recipient can no longer access /channel/api/*)."""
    try:
        from stock import channel as _channel

        conn = get_conn()
        ok = _channel.revoke_token(conn, token)
        if ok:
            typer.echo(f"Revoked: {token[:16]}...")
        else:
            typer.echo("No matching active token.", err=True)
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker symbol."""
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise typer.BadParameter(f"Invalid ticker '{ticker}': must be 1-5 uppercase letters.")
    return ticker


@ingest_app.command("news")
def ingest_news_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol (e.g. AAPL)")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print without writing to DB")
    ] = False,
) -> None:
    """Fetch news for a ticker from Yahoo + RSS feeds."""
    try:
        ticker = _validate_ticker(ticker)
        conn = get_conn()
        result = fetch_news(ticker, conn, dry_run=dry_run)
        typer.echo(
            f"News ingest: fetched={result.fetched} inserted={result.inserted}"
            f" skipped={result.skipped}"
        )
    except typer.BadParameter:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@ingest_app.command("prices")
def ingest_prices_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol (e.g. AAPL)")],
    days: Annotated[int, typer.Option(help="Number of days of history")] = 30,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print without writing to DB")
    ] = False,
) -> None:
    """Fetch daily OHLCV prices for a ticker."""
    try:
        ticker = _validate_ticker(ticker)
        conn = get_conn()
        result = fetch_prices(ticker, conn, days=days, dry_run=dry_run)
        typer.echo(
            f"Price ingest: fetched={result.fetched} inserted={result.inserted}"
            f" skipped={result.skipped}"
        )
    except typer.BadParameter:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("predict")
def predict_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol (e.g. AAPL)")],
) -> None:
    """Run a single-ticker prediction cycle."""
    try:
        ticker = _validate_ticker(ticker)
        conn = get_conn()
        result = predict_ticker(ticker, conn)
        typer.echo(
            f"Prediction: {result.ticker} {result.direction} "
            f"(prob_up={result.prob_up:.2f}, confidence={result.confidence:.2f})"
        )
        typer.echo(f"  Rationale: {result.rationale}")
        typer.echo(f"  Due at: {result.due_at}")
    except typer.BadParameter:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("score")
def score_cmd() -> None:
    """Score all due predictions and write outcome rows."""
    try:
        conn = get_conn()
        result = score_due(conn)
        typer.echo(
            f"Scoring: scored={result.scored} skipped={result.skipped}"
            f" already_scored={result.already_scored}"
        )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("report")
def report_cmd(
    days: Annotated[int, typer.Option("--days", help="Number of days to include")] = 7,
) -> None:
    """Print a performance report for the last N days."""
    try:
        conn = get_conn()
        report = build_report(conn, days=days)
        typer.echo(format_report(report))
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("reflect")
def reflect_cmd(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print proposed rules without writing")
    ] = False,
) -> None:
    """Run weekly reflection to update prediction rules."""
    try:
        conn = get_conn()
        result = reflect_weekly(conn, dry_run=dry_run)
        if dry_run:
            typer.echo("--- Proposed rules (dry run) ---")
            typer.echo(result.rules_text)
            typer.echo("--- End proposed rules ---")
        typer.echo(
            f"Reflection: version={result.version} model={result.model}"
            f" predictions={result.prediction_count} dry_run={result.dry_run}"
        )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("discover")
def discover_cmd(
    layer: Annotated[
        str | None,
        typer.Option("--layer", help="Force a focus layer (default: rotate by day-of-year)"),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option("--query", help="Optional extra query to prepend to the auto-batch"),
    ] = None,
    show: Annotated[
        bool,
        typer.Option("--show", help="Print extracted mentions/themes after the run"),
    ] = True,
) -> None:
    """Run a web-discovery cycle (search APIs + page fetch + LLM extraction)."""
    try:
        conn = get_conn()
        result = run_discovery(conn, focus_layer_name=layer, extra_query=query)
        typer.echo(
            f"Discovery id={result.research_id} session={result.session_label}"
            f" layer={result.layer_focus} queries={len(result.queries)}"
            f" mentions={len(result.extraction.mentions)}"
            f" themes={len(result.extraction.themes)}"
            f" cost=${result.cost_usd:.4f}"
        )
        if show:
            typer.echo("--- Mentions ---")
            for m in result.extraction.mentions:
                tag = " [under-followed]" if m.is_small_cap_or_under_followed else ""
                typer.echo(
                    f"  {m.ticker} ({m.layer}/{m.sublayer}){tag} -- {m.company} -- {m.conviction}"
                )
                typer.echo(f"    {m.thesis}")
            typer.echo("--- Themes ---")
            for t in result.extraction.themes:
                typer.echo(f"  {t.theme}: {t.summary}")
    except WebSearchUnavailable as exc:
        typer.echo(f"Web search unavailable: {exc}", err=True)
        raise typer.Exit(code=2)
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("research")
def research_cmd(
    layer: Annotated[
        str | None,
        typer.Option("--layer", help="Force a focus layer (default: rotate by day-of-year)"),
    ] = None,
    push: Annotated[
        bool,
        typer.Option("--push", help="Broadcast the report to enabled WeChat recipients"),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--lang", help="Output language ('zh' or 'en'); default from settings"),
    ] = None,
) -> None:
    """Generate the daily AI-supply-chain research note. Optional --push to WeChat."""
    try:
        conn = get_conn()
        report = generate_daily_research(
            conn, focus_layer_name=layer, language=language
        )
        typer.echo(
            f"Research id={report.research_id} layer={report.layer_focus}"
            f" cost=${report.cost_usd:.4f}"
        )
        typer.echo("--- Body ---")
        typer.echo(report.body)
        typer.echo("--- End body ---")

        if push:
            result = broadcast(report.body, conn, research_id=report.research_id)
            typer.echo(
                f"Push: sent={result.sent} failed={result.failed} queued={result.queued}"
            )
            for r in result.results:
                typer.echo(f"  -> {r.recipient}: {r.status} ({r.detail})")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("deep-dive")
def deep_dive_cmd(
    topic: Annotated[str, typer.Argument(help="Topic, layer name, sublayer, or ticker")],
    extra_context: Annotated[
        str | None,
        typer.Option("--note", help="Optional analyst note to attach to the prompt"),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--lang", help="Output language; default from settings"),
    ] = None,
    push: Annotated[
        bool,
        typer.Option("--push", help="Broadcast the deep-dive to WeChat recipients"),
    ] = False,
) -> None:
    """Run an on-demand deep-dive (e.g. 'china_osat_packaging', 'pam4_dsp_retimer')."""
    try:
        conn = get_conn()
        report = generate_deep_dive(
            conn, topic=topic, extra_context=extra_context, language=language
        )
        typer.echo(
            f"Deep dive id={report.research_id} topic={report.topic}"
            f" cost=${report.cost_usd:.4f}"
        )
        typer.echo("--- Body ---")
        typer.echo(report.body)
        typer.echo("--- End body ---")

        if push:
            result = broadcast(report.body, conn, research_id=report.research_id)
            typer.echo(
                f"Push: sent={result.sent} failed={result.failed} queued={result.queued}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("chain")
def chain_cmd(
    layer: Annotated[
        str | None,
        typer.Option("--layer", help="Print the players in a specific layer"),
    ] = None,
) -> None:
    """Inspect the AI supply chain map."""
    try:
        chain = load_chain()
        if layer is None:
            counts = chain_summary_for_log(chain)
            typer.echo(
                f"Supply chain: {counts['layers']} layers,"
                f" {counts['sublayers']} sublayers, {counts['players']} players"
            )
            typer.echo("Layers (rotate daily):")
            for name in list_layer_names(chain):
                typer.echo(f"  - {name}")
            return

        target = chain.find_layer(layer)
        if target is None:
            typer.echo(f"No layer '{layer}'. Available: {list_layer_names(chain)}")
            raise typer.Exit(code=1)
        typer.echo(f"# {target.layer} -- {target.function}")
        typer.echo(format_layer_players(target))
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("push")
def push_cmd(
    recipient: Annotated[
        str | None,
        typer.Argument(help="Recipient alias (default: every enabled recipient)"),
    ] = None,
    kind: Annotated[
        str,
        typer.Option("--kind", help="Which stored report to push: daily | deep_dive"),
    ] = "daily",
) -> None:
    """Push the latest stored research note to one or all enabled WeChat recipients."""
    try:
        conn = get_conn()
        report = get_latest_report(conn, kind=kind)
        if report is None:
            typer.echo(f"No stored report of kind={kind} -- run 'stock research' first.", err=True)
            raise typer.Exit(code=1)

        if recipient is None:
            result = broadcast(report.body, conn, research_id=report.research_id)
            typer.echo(
                f"Broadcast: sent={result.sent} failed={result.failed} queued={result.queued}"
            )
            for r in result.results:
                typer.echo(f"  -> {r.recipient}: {r.status}")
            return

        targets = [r for r in load_recipients() if r.alias == recipient]
        if not targets:
            typer.echo(f"Recipient '{recipient}' not enabled in wechat_recipients.yaml", err=True)
            raise typer.Exit(code=1)

        send = send_message(
            targets[0].alias, report.body, conn, research_id=report.research_id
        )
        typer.echo(f"-> {send.recipient}: {send.status} ({send.detail})")
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("deliver")
def deliver_cmd(
    skip_countdown: Annotated[
        bool,
        typer.Option("--now", help="Skip the 5-second move-your-mouse countdown"),
    ] = False,
    use_openclaw: Annotated[
        bool,
        typer.Option("--openclaw", help="Use the OpenClaw subprocess path instead of pyautogui"),
    ] = False,
) -> None:
    """Deliver every pending WeChat outbox task by driving the GUI directly (pyautogui)."""
    try:
        pending = list_pending_outbox()
        if not pending:
            typer.echo("Outbox empty -- nothing to deliver.")
            return
        typer.echo(f"Pending tasks ({len(pending)}):")
        for t in pending:
            typer.echo(f"  - {t.get('recipient')} | {Path(t.get('_task_path','')).name}")

        if use_openclaw:
            ok, detail = trigger_openclaw_delivery()
            if ok:
                typer.echo(f"OpenClaw triggered: {detail}")
            else:
                typer.echo(f"OpenClaw trigger failed: {detail}", err=True)
                raise typer.Exit(code=1)
            return

        # Default path: drive WeChat GUI directly via pyautogui
        result = gui_deliver_pending(skip_countdown=skip_countdown)
        typer.echo(f"GUI delivery: delivered={result.delivered} failed={result.failed}")
        for r in result.records:
            tag = "OK " if r.status == "delivered" else "ERR"
            extra = f" (proof: {r.proof_path})" if r.proof_path else ""
            typer.echo(f"  {tag} {r.recipient} -- {r.detail}{extra}")
        if result.failed and not result.delivered:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("pull-feedback")
def pull_feedback_cmd() -> None:
    """Open WeChat for each recipient and snapshot their chat (for boss-reply review)."""
    try:
        captures = pull_chat_screenshots()
        if not captures:
            typer.echo("No recipients enabled in data/wechat_recipients.yaml")
            return
        typer.echo(f"Inbox snapshots: {len(captures)}")
        for c in captures:
            typer.echo(f"  - {c.recipient}: {c.note}")
            if c.path:
                typer.echo(f"    -> {c.path}")
        typer.echo(
            "Open the screenshots, transcribe relevant boss replies, then run:\n"
            "  stock add-feedback <recipient> \"<their reply text>\"\n"
            "Recorded feedback is auto-injected into the next research note."
        )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("add-feedback")
def add_feedback_cmd(
    recipient: Annotated[str, typer.Argument(help="Recipient alias from wechat_recipients.yaml")],
    text: Annotated[str, typer.Argument(help="The reader's feedback text (quote the reply)")],
    source: Annotated[
        str, typer.Option("--source", help="Where the feedback came from (default: manual)"),
    ] = "manual",
) -> None:
    """Append a feedback entry to data/wechat_feedback.md (auto-included in next research)."""
    try:
        path = append_feedback(recipient, text, source=source)
        typer.echo(f"Recorded feedback in {path}")
        entries = read_feedback_entries(lookback_days=14)
        typer.echo(f"Total entries (last 14 days): {len(entries)}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("outbox")
def outbox_cmd(
    mark_sent: Annotated[
        str | None,
        typer.Option("--mark-sent", help="Filename of a pending task to mark delivered"),
    ] = None,
    notes: Annotated[
        str | None,
        typer.Option("--notes", help="Optional delivery notes when marking sent"),
    ] = None,
) -> None:
    """List pending WeChat outbox tasks (or mark one delivered)."""
    try:
        if mark_sent:
            ok = mark_outbox_delivered(mark_sent, notes=notes)
            if ok:
                typer.echo(f"Marked delivered: {mark_sent}")
                return
            typer.echo(f"Could not mark {mark_sent} (not found or unreadable)", err=True)
            raise typer.Exit(code=1)

        pending = list_pending_outbox()
        if not pending:
            typer.echo("Outbox empty (no pending tasks).")
            return
        typer.echo(f"Pending tasks: {len(pending)}")
        for task in pending:
            typer.echo(
                f"  {task.get('recipient')} | queued {task.get('queued_at', '?')[:16]}"
                f" | {task.get('body_chars', '?')} chars"
                f" | task: {Path(task.get('_task_path', '')).name}"
            )
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("serve")
def serve_cmd(
    api_only: Annotated[
        bool,
        typer.Option("--api-only", help="Run only the FastAPI server, not the scheduler"),
    ] = False,
    scheduler_only: Annotated[
        bool,
        typer.Option("--scheduler-only", help="Run only the scheduler, not the API"),
    ] = False,
) -> None:
    """Run the orchestrator (scheduler) and the FastAPI server together."""
    # Lazy imports keep non-serve commands fast
    import threading

    from stock.api import run_api
    from stock.orchestrator import run_orchestrator

    try:
        # Reject contradictory flags before booting anything
        if api_only and scheduler_only:
            raise typer.BadParameter(
                "--api-only and --scheduler-only are mutually exclusive"
            )

        # API-only mode: block in uvicorn, no scheduler at all
        if api_only:
            run_api()
            return

        # Default + scheduler_only: start API on a daemon thread unless disabled
        if not scheduler_only:
            api_thread = threading.Thread(target=run_api, name="stock-api", daemon=True)
            api_thread.start()

        run_orchestrator()
    except typer.BadParameter:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@queue_app.command("list")
def action_queue_list_cmd() -> None:
    """Print pending + last-24h completed action_queue rows."""
    try:
        conn = get_conn()
        pend = action_queue.pending_items(conn)
        done = action_queue.recent_completed(conn, hours=24)
        typer.echo(f"Pending: {len(pend)}")
        for item in pend:
            typer.echo(f"  - id={item.id} | {item.topic[:80]}")
        typer.echo(f"Recently completed (24h): {len(done)}")
        for item in done:
            tag = f"deep_dive_id={item.deep_dive_id}" if item.deep_dive_id else "no body"
            typer.echo(f"  - id={item.id} | {item.topic[:80]} | {tag}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@queue_app.command("run")
def action_queue_run_cmd(
    max_items: Annotated[
        int, typer.Option("--max", help="Max pending rows to drain in this run"),
    ] = 4,
) -> None:
    """Drain up to N pending action_queue rows by running them as deep-dives."""
    try:
        conn = get_conn()
        completed = action_queue.run_pending(conn, max_items=max_items)
        typer.echo(f"Drained: {len(completed)}")
        for item in completed:
            typer.echo(f"  - {item.status} | {item.topic[:80]}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@queue_app.command("clear")
def action_queue_clear_cmd(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Only delete rows with this status (default: all)"),
    ] = None,
) -> None:
    """Delete rows from the action_queue table (optionally filtered by status)."""
    try:
        conn = get_conn()
        deleted = action_queue.clear(conn, status=status)
        typer.echo(f"Deleted {deleted} row(s)")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@holding_app.command("add")
def holding_add_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker (e.g. NVDA)")],
    qty: Annotated[float, typer.Argument(help="Share quantity")],
    cost_basis: Annotated[float, typer.Argument(help="Average cost per share")],
    notes: Annotated[
        str, typer.Option("--notes", help="Optional free-text note"),
    ] = "",
) -> None:
    """Insert or update a tracked holding."""
    try:
        conn = get_conn()
        h = holdings.add_holding(
            conn, ticker=ticker, qty=qty, cost_basis=cost_basis, notes=notes
        )
        typer.echo(f"Holding upserted: {h.ticker} qty={h.qty} cost={h.cost_basis}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@holding_app.command("remove")
def holding_remove_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to deactivate")],
) -> None:
    """Mark a holding inactive (kept for audit trail)."""
    try:
        conn = get_conn()
        ok = holdings.remove_holding(conn, ticker)
        if ok:
            typer.echo(f"Removed: {ticker.upper()}")
        else:
            typer.echo(f"No matching row for {ticker}")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@holding_app.command("list")
def holding_list_cmd() -> None:
    """List active tracked holdings."""
    try:
        conn = get_conn()
        rows = holdings.list_holdings(conn, active_only=True)
        if not rows:
            typer.echo("No active holdings.")
            return
        for h in rows:
            typer.echo(
                f"  - {h.ticker} | qty={h.qty:g} | cost={h.cost_basis:.2f}"
                f" | notes={h.notes}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@holding_app.command("note")
def holding_note_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to annotate")],
    note: Annotated[str, typer.Argument(help="Free-text note")],
) -> None:
    """Update the notes column on a holding."""
    try:
        conn = get_conn()
        ok = holdings.set_note(conn, ticker, note)
        if ok:
            typer.echo(f"Note updated for {ticker.upper()}")
        else:
            typer.echo(f"No matching row for {ticker}")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("anomaly-run")
def anomaly_run_cmd() -> None:
    """Recompute today's price/volume anomalies."""
    try:
        conn = get_conn()
        rows = anomaly.compute_daily_anomalies(conn)
        typer.echo(f"Flagged: {len(rows)}")
        for row in rows:
            pct = f"{row.pct_change * 100:+.2f}%"
            typer.echo(
                f"  - [{row.ts}] {row.ticker} pct={pct} vol={row.volume_ratio:.2f}x"
                f" reason={row.flag_reason}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


# Allow `python -m stock.cli ...` to invoke the typer app
if __name__ == "__main__":
    app()
