"""stock.cli -- typer CLI for the stock prediction pipeline."""
from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Annotated

import typer

from stock import action_queue, anomaly, discovery_engine, grading, holdings, thesis as thesis_mod
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
self_review_app = typer.Typer(help="Daily self-review packet + Claude/MiniMax proposals.")
app.add_typer(self_review_app, name="self-review")


@self_review_app.command("compile")
def self_review_compile_cmd(
    date: Annotated[
        str | None,
        typer.Option("--date", help="Target date YYYY-MM-DD (defaults to today UTC)"),
    ] = None,
    print_body: Annotated[
        bool, typer.Option("--print", help="Echo the packet body to stdout")
    ] = False,
) -> None:
    """Compile pipeline/daily_review_YYYY-MM-DD.md from the local DB."""
    try:
        from stock import self_review as _sr

        conn = get_conn()
        result = _sr.compile_daily_packet(conn, date=date)
        typer.echo(f"Wrote {result.path} ({len(result.body)} bytes)")
        if print_body:
            typer.echo("---")
            typer.echo(result.body)
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@self_review_app.command("run")
def self_review_run_cmd(
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help="Override SELF_REVIEW_BACKEND (claude_code | minimax | both | off)",
        ),
    ] = "",
) -> None:
    """Run today's review using the configured backend (or override via --backend)."""
    try:
        from stock import self_review as _sr

        conn = get_conn()
        if backend:
            # Honor a one-shot override without mutating .env
            from stock.config import get_settings

            settings = get_settings()
            settings.self_review_backend = backend
        result = _sr.run_daily_review(conn)
        if not result.path:
            typer.echo("Self-review skipped (backend=off)")
            return
        typer.echo(f"Packet: {result.path}")
        proposals = _sr.list_proposals(conn, review_date=result.date, only_unapplied=True)
        if proposals:
            typer.echo(f"Proposals stored ({len(proposals)}):")
            for p in proposals:
                typer.echo(
                    f"  #{p['id']} [{p['impact']}/{p['risk']}] {p['title']}"
                )
        else:
            typer.echo("No proposals stored.")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@self_review_app.command("proposals")
def self_review_proposals_cmd(
    date: Annotated[
        str | None,
        typer.Option("--date", help="Filter by review_date YYYY-MM-DD"),
    ] = None,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include already-applied proposals")
    ] = False,
    detail: Annotated[
        bool, typer.Option("--detail", help="Print full rationale + diff_or_steps"),
    ] = False,
) -> None:
    """List recent self-review proposals."""
    try:
        from stock import self_review as _sr

        conn = get_conn()
        rows = _sr.list_proposals(
            conn, review_date=date, only_unapplied=not show_all, limit=50
        )
        if not rows:
            typer.echo("No proposals.")
            return
        for p in rows:
            typer.echo(
                f"#{p['id']} {p['review_date']} [{p['impact']}/{p['risk']}]"
                f" {p['backend']}: {p['title']}"
            )
            if detail:
                typer.echo(f"  rationale: {p['rationale']}")
                typer.echo(f"  files: {', '.join(str(f) for f in p['files'])}")
                typer.echo(f"  steps:\n{p['diff_or_steps']}")
                typer.echo("")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@self_review_app.command("apply")
def self_review_apply_cmd(
    proposal_id: Annotated[int, typer.Argument(help="Proposal id to mark as applied")],
    notes: Annotated[
        str, typer.Option("--notes", help="Free-text note about how it was applied")
    ] = "",
) -> None:
    """Mark a proposal as applied (after you've actually made the code change)."""
    try:
        from stock import self_review as _sr

        conn = get_conn()
        ok = _sr.mark_applied(conn, proposal_id, notes=notes)
        if ok:
            typer.echo(f"Marked #{proposal_id} as applied")
        else:
            typer.echo("No matching unapplied proposal.", err=True)
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


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


@app.command("sync")
def sync_cmd() -> None:
    """Push local research notes + tokens to Render and pull any boss replies.

    Runs the same logic as the scheduled `_job_sync_to_render` job, but on demand.
    Useful for: bootstrapping after minting tokens, or when you want to confirm
    the cloud_proxy is reachable.
    """
    try:
        from stock.cloud_sync import run_local_sync

        conn = get_conn()
        result = run_local_sync(conn)
        if result.error:
            typer.echo(f"sync failed: {result.error}", err=True)
            raise typer.Exit(code=1)
        typer.echo(
            f"sync ok: notes_pushed={result.notes_pushed}"
            f" tokens_pushed={result.tokens_pushed}"
            f" replies_pulled={result.replies_pulled}"
        )
    except typer.Exit:
        raise
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


@app.command("grade")
def grade_cmd(
    hours: Annotated[
        int, typer.Option("--hours", help="Lookback window for scored predictions"),
    ] = grading.DEFAULT_LOOKBACK_HOURS,
    no_refresh: Annotated[
        bool, typer.Option("--no-refresh", help="Skip the yfinance price refresh step"),
    ] = False,
    no_score: Annotated[
        bool, typer.Option("--no-score", help="Skip score_due before reading outcomes"),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--lang", help="Output language ('zh' or 'en'); default from settings"),
    ] = None,
) -> None:
    """Run the daily grade-and-reply: refresh prices, score, generate grading note."""
    try:
        conn = get_conn()
        note = grading.generate_grading_note(
            conn,
            lookback_hours=hours,
            refresh_prices=not no_refresh,
            score_first=not no_score,
            language=language,
        )
        typer.echo(
            f"Grading id={note.research_id} total={note.stats.total}"
            f" hits={note.stats.hits} hit_rate={note.stats.hit_rate:.1%}"
            f" refreshed={len(note.refreshed.tickers)}"
            f" follow_ups={note.follow_ups_queued}"
            f" cost=${note.cost_usd:.4f}"
        )
        if note.refreshed.failed:
            typer.echo(f"  refresh failed: {', '.join(note.refreshed.failed)}")
        typer.echo("--- Body ---")
        typer.echo(note.body)
        typer.echo("--- End body ---")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


thesis_app = typer.Typer(help="Thesis tracking + post-hoc claim verification (F16).")
app.add_typer(thesis_app, name="thesis")

backend_app = typer.Typer(help="Inspect / switch the core LLM backend (F17).")
app.add_typer(backend_app, name="backend")

event_app = typer.Typer(help="Tracked event-prediction calendar (F26).")
app.add_typer(event_app, name="event")


@event_app.command("add")
def event_add_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker (e.g. NVDA)")],
    event_type: Annotated[str, typer.Argument(help="earnings | guidance | product_launch | regulatory | contract_win | supply_chain | macro | insider_action | policy | other")],
    title: Annotated[str, typer.Argument(help="Short event title (e.g. 'NVDA Q3 earnings print')")],
    predicted_outcome: Annotated[str, typer.Argument(help="What we expect to happen (e.g. 'Revenue beat by 5%+ and FY guidance raise')")],
    window_start: Annotated[str, typer.Argument(help="ISO date YYYY-MM-DD")],
    window_end: Annotated[str, typer.Argument(help="ISO date YYYY-MM-DD")],
    confidence: Annotated[float, typer.Option("--confidence", help="0.0-1.0")] = 0.6,
    source_research_id: Annotated[
        int | None, typer.Option("--source", help="research_reports.id this prediction came from"),
    ] = None,
    notes: Annotated[str, typer.Option("--notes", help="Free-text notes")] = "",
) -> None:
    """Add a new tracked event prediction."""
    try:
        from stock import events as _ev
        conn = get_conn()
        ev = _ev.add_event(
            conn, ticker=ticker, event_type=event_type, title=title,
            predicted_outcome=predicted_outcome,
            window_start=window_start, window_end=window_end,
            confidence=confidence, source_research_id=source_research_id,
            notes=notes or None,
        )
        typer.echo(f"Added event #{ev.id}: {ev.ticker} {ev.event_type} -> {ev.window_end}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@event_app.command("list")
def event_list_cmd(
    status: Annotated[
        str | None, typer.Option("--status", help="pending | hit | miss | partial | expired | cancelled"),
    ] = None,
    ticker: Annotated[str | None, typer.Option("--ticker", help="Filter by ticker")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """List tracked events with optional filters."""
    try:
        from stock import events as _ev
        conn = get_conn()
        rows = _ev.list_events(conn, status=status, ticker=ticker, limit=limit)
        if not rows:
            typer.echo("(no events)")
            return
        for e in rows:
            tag = {
                "pending": "PEND", "hit": " HIT", "miss": "MISS",
                "partial": "PART", "expired": "EXPR", "cancelled": "CXLD",
            }.get(e.status, "????")
            typer.echo(
                f"#{e.id:<4} [{tag}] {e.ticker:<10} {e.event_type:<14}"
                f" win={e.window_start[:10]}->{e.window_end[:10]}"
                f" conf={e.confidence:.2f}  {e.title[:60]}"
            )
            if e.actual_outcome:
                typer.echo(f"        actual: {e.actual_outcome[:120]}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@event_app.command("edit")
def event_edit_cmd(
    event_id: Annotated[int, typer.Argument(help="Event id")],
    title: Annotated[str | None, typer.Option("--title")] = None,
    predicted_outcome: Annotated[str | None, typer.Option("--outcome")] = None,
    window_start: Annotated[str | None, typer.Option("--start")] = None,
    window_end: Annotated[str | None, typer.Option("--end")] = None,
    confidence: Annotated[float | None, typer.Option("--confidence")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Force-set status (pending/hit/miss/partial/expired/cancelled)")] = None,
    notes: Annotated[str | None, typer.Option("--notes")] = None,
) -> None:
    """Edit an existing tracked event."""
    try:
        from stock import events as _ev
        conn = get_conn()
        fields: dict[str, object] = {}
        if title is not None: fields["title"] = title
        if predicted_outcome is not None: fields["predicted_outcome"] = predicted_outcome
        if window_start is not None: fields["window_start"] = window_start
        if window_end is not None: fields["window_end"] = window_end
        if confidence is not None: fields["confidence"] = confidence
        if status is not None: fields["status"] = status
        if notes is not None: fields["notes"] = notes
        ok = _ev.edit_event(conn, event_id, **fields)
        typer.echo(f"Updated event #{event_id}" if ok else "No matching row.")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@event_app.command("delete")
def event_delete_cmd(
    event_id: Annotated[int, typer.Argument(help="Event id to delete")],
) -> None:
    """Hard-delete a tracked event."""
    try:
        from stock import events as _ev
        conn = get_conn()
        ok = _ev.delete_event(conn, event_id)
        typer.echo(f"Deleted event #{event_id}" if ok else "No matching row.")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@event_app.command("verify")
def event_verify_cmd(
    event_id: Annotated[int | None, typer.Argument(help="Event id; omit to verify ALL pending")] = None,
    max_items: Annotated[int, typer.Option("--max")] = 30,
) -> None:
    """Verify pending event(s) against post-window news + filings."""
    try:
        from stock import events as _ev
        conn = get_conn()
        if event_id is not None:
            ev = _ev.verify_event(conn, event_id)
            typer.echo(f"#{event_id} verdict: {ev.status if ev else 'no row'}")
        else:
            graded = _ev.verify_due_events(conn, max_items=max_items)
            typer.echo(f"Verified {len(graded)} due event(s)")
            for ev in graded:
                typer.echo(f"  #{ev.id} {ev.ticker} -> {ev.status}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@event_app.command("calibration")
def event_calibration_cmd(
    days: Annotated[int, typer.Option("--days")] = 90,
) -> None:
    """Show hit-rate stats for resolved events."""
    try:
        from stock import events as _ev
        conn = get_conn()
        s = _ev.event_calibration_summary(conn, lookback_days=days)
        typer.echo(f"Resolved events (last {s['lookback_days']}d): {s['total_resolved']}")
        typer.echo(f"  hits     : {s['hits']}")
        typer.echo(f"  misses   : {s['misses']}")
        typer.echo(f"  partial  : {s['partials']}")
        typer.echo(f"  expired  : {s['expired']}")
        typer.echo(f"  hit rate : {s['hit_rate']:.1%}")
        typer.echo(f"  avg conf : {s['avg_confidence_when_resolved']:.2f}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)

discover_app = typer.Typer(help="Forward-looking discovery engine (F19) -- find before it explodes.")
app.add_typer(discover_app, name="forward-discover")


@discover_app.command("run")
def forward_discover_run_cmd(
    no_promote: Annotated[
        bool, typer.Option("--no-promote", help="Score only; don't auto-add to watchlist"),
    ] = False,
) -> None:
    """Run one full forward-discovery pass (score universe, persist, optionally promote)."""
    try:
        conn = get_conn()
        result = discovery_engine.run_discovery_engine(
            conn, auto_promote=not no_promote,
        )
        typer.echo(
            f"Universe={result.universe_size} scored={result.scored}"
            f" new={result.new_candidates} updated={result.updated_candidates}"
            f" promoted={result.promoted_tickers or 'none'}"
            f" apewisdom_ok={result.apewisdom_hit}"
        )
        typer.echo("--- Top candidates ---")
        for cs in result.top_candidates:
            gate = "GATE" if cs.qap_gate else "no-gate"
            typer.echo(
                f"  {cs.ticker}  FWP={cs.fwp:.3f}  [{gate}]"
                f"  ocis={cs.components.get('ocis_raw', 0):.1f}"
                f"  cluster={int(cs.components.get('ocis_cluster_max', 0))}"
                f"  novelty={cs.components.get('novelty_raw', 0):.2f}"
                f"  reddit_accel={cs.components.get('reddit_accel', 0):+.2f}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@discover_app.command("list")
def forward_discover_list_cmd(
    status: Annotated[
        str | None, typer.Option("--status", help="Filter: candidate|promoted|dismissed"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows")] = 50,
) -> None:
    """Show stored discovery candidates ordered by FWP score."""
    try:
        conn = get_conn()
        rows = discovery_engine.list_candidates(conn, status=status, limit=limit)
        if not rows:
            typer.echo("(no candidates)")
            return
        for cs in rows:
            gate = "GATE" if cs.qap_gate else "no-gate"
            typer.echo(
                f"  {cs.ticker:<10} FWP={cs.fwp:.3f}  [{gate}]"
                f"  scored_at={cs.score_at[:16]}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@discover_app.command("dismiss")
def forward_discover_dismiss_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to dismiss (won't be re-promoted for 30d)")],
    reason: Annotated[str, typer.Option("--reason", help="Free-text reason")] = "",
) -> None:
    """Dismiss a candidate (operator decided it's noise / wrong / illiquid)."""
    try:
        conn = get_conn()
        ok = discovery_engine.dismiss_candidate(conn, ticker, reason=reason)
        typer.echo(f"Dismissed {ticker.upper()}" if ok else "No matching row.")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@discover_app.command("backtest-winners")
def forward_discover_backtest_cmd(
    out_dir: Annotated[
        str, typer.Option("--out-dir", help="Where to write the markdown report"),
    ] = "pipeline",
) -> None:
    """F20 diagnostic: would F19's signals have fired before known winners broke out?"""
    try:
        from stock import backtest_winners as _bt

        conn = get_conn()
        path = _bt.write_diagnostic_report(conn, out_dir=out_dir)
        typer.echo(f"Wrote {path}")
        # Echo the table to stdout for quick inspection
        typer.echo("---")
        typer.echo(Path(path).read_text(encoding="utf-8"))
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@discover_app.command("promote")
def forward_discover_promote_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to promote to active watchlist")],
) -> None:
    """Manually promote a candidate (override the gates)."""
    try:
        conn = get_conn()
        rows = discovery_engine.list_candidates(conn, limit=200)
        match = next((c for c in rows if c.ticker == ticker.upper()), None)
        score = match.fwp if match else 0.0
        discovery_engine.promote_candidate(conn, ticker, score=score)
        typer.echo(f"Promoted {ticker.upper()} (FWP={score:.3f})")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@backend_app.command("show")
def backend_show_cmd() -> None:
    """Print the active core backend + model + smoke-test that it's reachable."""
    try:
        from stock.config import get_settings as _get_settings
        from stock.models import (
            CLAUDE_CLI_CORE_BIN,
            ClaudeCliClient,
            ClaudeCliUnavailable,
            get_core_client,
            get_core_model,
        )

        settings = _get_settings()
        typer.echo(f"core_llm_backend = {settings.core_llm_backend}")
        typer.echo(f"core model       = {get_core_model()}")
        client = get_core_client()
        typer.echo(f"client provider  = {client.provider}")
        typer.echo(f"minimax key set  = {bool(settings.minimax_api_key)}")
        typer.echo(f"claude_cli bin   = {CLAUDE_CLI_CORE_BIN}")

        # Probe the binary if claude_cli is selected
        if isinstance(client, ClaudeCliClient):
            import shutil

            found = shutil.which(CLAUDE_CLI_CORE_BIN)
            if found:
                typer.echo(f"claude found at  = {found}")
            else:
                typer.echo(
                    f"WARNING: `{CLAUDE_CLI_CORE_BIN}` not on PATH;"
                    f" core calls will fall back to MiniMax."
                )
                raise typer.Exit(code=2)
        _ = ClaudeCliUnavailable  # silence unused-import linter
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@backend_app.command("set")
def backend_set_cmd(
    backend: Annotated[
        str, typer.Argument(help="Backend name: minimax | claude_cli"),
    ],
) -> None:
    """Update CORE_LLM_BACKEND in .env (creates the file if missing).

    The change takes effect for *new* processes. Restart the orchestrator
    (`stock serve` / the gateway) to pick it up. Existing in-flight calls keep
    using the previous backend.
    """
    backend = backend.strip().lower()
    if backend not in ("minimax", "claude_cli"):
        typer.echo(
            f"Backend must be 'minimax' or 'claude_cli', got '{backend}'.", err=True,
        )
        raise typer.Exit(code=1)

    env_path = Path(".env")
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    seen = False
    for line in lines:
        if line.strip().startswith("CORE_LLM_BACKEND="):
            new_lines.append(f"CORE_LLM_BACKEND={backend}")
            seen = True
        else:
            new_lines.append(line)
    if not seen:
        new_lines.append(f"CORE_LLM_BACKEND={backend}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    typer.echo(f"Wrote CORE_LLM_BACKEND={backend} to {env_path.resolve()}")
    typer.echo("Restart the orchestrator + gateway to pick up the change.")


@backend_app.command("test")
def backend_test_cmd(
    prompt: Annotated[
        str,
        typer.Option("--prompt", help="Test prompt to send"),
    ] = "Reply with the single word OK and nothing else.",
) -> None:
    """Send one tiny chat call to the active backend and print the response."""
    try:
        from stock.models import (
            ChatMessage,
            ClaudeCliUnavailable,
            get_core_client,
            get_core_model,
        )

        conn = get_conn()
        client = get_core_client()
        msgs: list[ChatMessage] = [{"role": "user", "content": prompt}]
        try:
            response = client.chat(
                messages=msgs,
                model=get_core_model(),
                max_tokens=128,
                conn=conn,
                caller="cli.backend_test",
            )
        except ClaudeCliUnavailable as exc:
            typer.echo(f"claude_cli unavailable: {exc}", err=True)
            raise typer.Exit(code=2)
        typer.echo(
            f"provider={client.provider} model={response.model}"
            f" cost=${response.cost_usd:.4f}"
            f" tokens={response.input_tokens}+{response.output_tokens}"
        )
        typer.echo("--- response ---")
        typer.echo(response.content)
    except typer.Exit:
        raise
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@thesis_app.command("extract")
def thesis_extract_cmd(
    prediction_id: Annotated[int, typer.Argument(help="Prediction id to decompose")],
) -> None:
    """Extract atomic claims from a prediction's rationale (best-effort, idempotent)."""
    try:
        conn = get_conn()
        rows = thesis_mod.extract_theses(prediction_id, conn)
        typer.echo(f"Extracted {len(rows)} thesis row(s) for prediction {prediction_id}")
        for r in rows:
            typer.echo(f"  - [{r.claim_type}] {r.claim_text[:160]}")
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@thesis_app.command("verify")
def thesis_verify_cmd(
    max_items: Annotated[
        int, typer.Option("--max", help="Max ungraded theses to verify"),
    ] = 30,
) -> None:
    """Verify every ungraded thesis whose underlying prediction is now scored."""
    try:
        conn = get_conn()
        graded = thesis_mod.verify_due_theses(conn, max_items=max_items)
        typer.echo(f"Graded: {len(graded)}")
        for r in graded:
            typer.echo(
                f"  - thesis #{r.id} pred #{r.prediction_id} verdict={r.verdict}"
                f" conf={r.confidence:.2f}" if r.confidence is not None
                else f"  - thesis #{r.id} pred #{r.prediction_id} verdict={r.verdict}"
            )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@thesis_app.command("stats")
def thesis_stats_cmd(
    hours: Annotated[int, typer.Option("--hours", help="Lookback window")] = 36,
) -> None:
    """Print aggregated thesis-verdict stats for the recent window."""
    try:
        conn = get_conn()
        stats = thesis_mod.compute_thesis_stats(conn, hours=hours)
        typer.echo(thesis_mod.format_thesis_block(stats))
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@thesis_app.command("show")
def thesis_show_cmd(
    prediction_id: Annotated[int, typer.Argument(help="Prediction id")],
) -> None:
    """List all theses tied to a prediction with their verdicts and evidence."""
    try:
        conn = get_conn()
        rows = thesis_mod.list_for_prediction(conn, prediction_id)
        if not rows:
            typer.echo("(no theses)")
            return
        for r in rows:
            verdict = r.verdict or "pending"
            typer.echo(
                f"#{r.id} [{r.claim_type}] verdict={verdict}"
                f" conf={r.confidence:.2f}" if r.confidence is not None
                else f"#{r.id} [{r.claim_type}] verdict={verdict}"
            )
            typer.echo(f"  claim: {r.claim_text}")
            if r.verifiable_by:
                typer.echo(f"  verifiable_by: {r.verifiable_by}")
            if r.evidence_text:
                typer.echo(f"  evidence ({r.evidence_source}): {r.evidence_text}")
            if r.chain_consistency:
                typer.echo(
                    f"  chain_consistency: {r.chain_consistency}"
                    f" -- {r.chain_consistency_reason or ''}"
                )
    except Exception:
        typer.echo(traceback.format_exc(), err=True)
        raise typer.Exit(code=1)


@app.command("check")
def check_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to inspect (e.g. SMCI)")],
) -> None:
    """One-shot status snapshot for a ticker: price, stop, alerts, anomalies, events.

    Useful for quick "should I sell?" checks. Runs entirely on local data,
    no LLM calls -- always free, always fast.
    """
    try:
        ticker = ticker.upper()
        from datetime import datetime, timedelta, timezone
        from stock.events import list_events
        from stock.stops import compute_stop_loss

        conn = get_conn()
        now = datetime.now(timezone.utc)
        week_iso = (now - timedelta(days=7)).isoformat()
        fortnight_date = (now - timedelta(days=14)).strftime("%Y-%m-%d")

        typer.echo(f"=== {ticker} status snapshot ({now.isoformat(timespec='minutes')} UTC) ===")

        # 1) Recent prices
        rows = conn.execute(
            "SELECT ts, c, v FROM prices WHERE ticker = ? ORDER BY ts DESC LIMIT 5",
            (ticker,),
        ).fetchall()
        typer.echo("")
        typer.echo("--- last 5 daily closes ---")
        if rows:
            for r in rows:
                typer.echo(f"  {r[0]}  close=${r[1]:.2f}  vol={r[2]:,}")
        else:
            typer.echo("  (no price history; run `stock ingest prices " + ticker + "` first)")

        # 2) Stop-loss recommendation (F24)
        stop = compute_stop_loss(ticker, conn)
        typer.echo("")
        typer.echo("--- stop-loss reference (F24) ---")
        if stop.entry_price is not None:
            typer.echo(f"  entry (latest close): ${stop.entry_price:.2f}")
            typer.echo(f"  ATR(20):              ${stop.atr_20:.2f}" if stop.atr_20 is not None else "  ATR(20): N/A")
            typer.echo(f"  ATR-stop (2x):        ${stop.atr_stop:.2f}" if stop.atr_stop is not None else "  ATR-stop: N/A")
            typer.echo(f"  30d swing-low:        ${stop.swing_low_30d:.2f}" if stop.swing_low_30d is not None else "  swing-low: N/A")
            typer.echo(f"  -15% percent stop:    ${stop.percent_stop:.2f}" if stop.percent_stop is not None else "")
            if stop.recommended is not None:
                dist = (stop.entry_price - stop.recommended) / stop.entry_price * 100
                typer.echo(f"  RECOMMENDED:          ${stop.recommended:.2f}  ({dist:.1f}% below)")
        else:
            typer.echo(f"  {stop.rationale}")

        # 3) Holding info if tracked
        h_row = conn.execute(
            "SELECT qty, cost_basis, opened_at FROM holdings"
            " WHERE ticker = ? AND active = 1",
            (ticker,),
        ).fetchone()
        typer.echo("")
        typer.echo("--- holding info ---")
        if h_row:
            qty, cost, opened = h_row
            typer.echo(f"  qty={qty:g} cost=${cost:.2f} opened={opened}")
            if cost > 0 and stop.entry_price:
                pnl_pct = (stop.entry_price - cost) / cost * 100
                typer.echo(f"  P&L: {pnl_pct:+.1f}% (last ${stop.entry_price:.2f} vs cost ${cost:.2f})")
        else:
            typer.echo("  (not in active holdings -- add with `stock holding add`)")

        # 4) Sell-trigger alerts (F28)
        alert_rows = conn.execute(
            "SELECT id, topic, datetime(created_at) FROM research_reports"
            " WHERE kind = 'alert' AND COALESCE(topic, '') LIKE ? AND created_at >= ?"
            " ORDER BY created_at DESC LIMIT 5",
            (f"{ticker}%", week_iso),
        ).fetchall()
        typer.echo("")
        typer.echo(f"--- sell-trigger alerts (last 7d, F28) ---")
        if alert_rows:
            for r in alert_rows:
                typer.echo(f"  [#{r[0]}] {r[2]}  {r[1]}")
        else:
            typer.echo("  (none)")

        # 5) Anomaly flags
        anom_rows = conn.execute(
            "SELECT ts, pct_change, volume_ratio, flag_reason FROM price_anomalies"
            " WHERE ticker = ? AND ts >= ? ORDER BY ts DESC LIMIT 5",
            (ticker, fortnight_date),
        ).fetchall()
        typer.echo("")
        typer.echo("--- price/volume anomalies (last 14d, F12) ---")
        if anom_rows:
            for r in anom_rows:
                typer.echo(
                    f"  [{r[0]}] pct={r[1] * 100:+.2f}% vol={r[2]:.2f}x reason={r[3]}"
                )
        else:
            typer.echo("  (none flagged)")

        # 6) Recent news
        news_rows = conn.execute(
            "SELECT ts, title FROM news WHERE ticker = ? AND ts >= ?"
            " ORDER BY ts DESC LIMIT 6",
            (ticker, week_iso),
        ).fetchall()
        typer.echo("")
        typer.echo("--- news headlines (last 7d) ---")
        if news_rows:
            for r in news_rows:
                typer.echo(f"  [{r[0][:10]}] {r[1][:120]}")
        else:
            typer.echo("  (none ingested)")

        # 7) Tracked events
        events_for = list_events(conn, ticker=ticker, limit=10)
        typer.echo("")
        typer.echo("--- tracked events (F26) ---")
        if events_for:
            for e in events_for:
                tag = {
                    "pending": "PEND", "hit": " HIT", "miss": "MISS",
                    "partial": "PART", "expired": "EXPR", "cancelled": "CXLD",
                }.get(e.status, "????")
                typer.echo(
                    f"  #{e.id} [{tag}] {e.event_type:<14} window_end={e.window_end[:10]}"
                    f"  conf={e.confidence:.2f}  {e.title[:60]}"
                )
        else:
            typer.echo("  (no tracked events for this ticker)")

        # 8) Forward-discovery score
        fwp_row = conn.execute(
            "SELECT score, qap_gate, datetime(last_score_at), status"
            " FROM discovery_candidates WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        typer.echo("")
        typer.echo("--- forward-discovery (F19) ---")
        if fwp_row:
            gate = "GATE" if fwp_row[1] else "no-gate"
            typer.echo(
                f"  FWP={fwp_row[0]:.3f}  [{gate}]  status={fwp_row[3]}"
                f"  scored_at={fwp_row[2]}"
            )
        else:
            typer.echo("  (not in discovery candidates -- next refresh fires daily 23:00 UTC)")

        # 9) Insider Form 4
        ins_rows = conn.execute(
            "SELECT filed_at, filer_name, transaction_type, shares, price"
            " FROM insider_filings WHERE ticker = ?"
            " ORDER BY filed_at DESC LIMIT 5",
            (ticker,),
        ).fetchall()
        typer.echo("")
        typer.echo("--- insider Form 4 (last 5) ---")
        if ins_rows:
            for r in ins_rows:
                typer.echo(
                    f"  [{str(r[0])[:10]}] {r[1]} {r[2]} {r[3]} @ ${r[4]}"
                )
        else:
            typer.echo("  (none -- next EDGAR pull is Sundays 05:00 UTC)")
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
