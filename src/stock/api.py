"""stock.api -- FastAPI app on 127.0.0.1:18790 for OpenClaw skill tools."""
from __future__ import annotations

# stdlib
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

# third-party
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# internal
from stock import action_queue, anomaly, holdings
from stock.channel import (
    ChannelHTTPError,
    channel_exception_handler,
    create_router as create_channel_router,
)
from stock.cloud_sync import create_router as create_sync_router
from stock.config import get_settings
from stock.db import get_conn
from stock.discover import (
    DiscoverExtraction,
    DiscoverResult,
    get_latest_discovery,
    run_discovery,
)
from stock.models import CostCeilingError
from stock.predict import PredictionResult, predict_ticker
from stock.research import (
    generate_daily_research,
    generate_deep_dive,
    get_latest_report,
)
from stock.score import OutcomeDetail, build_report
from stock.supply_chain import (
    chain_summary_for_log,
    format_layer_players,
    list_layer_names,
    load_chain,
)
from stock.websearch import WebSearchUnavailable
from stock.wechat import (
    BroadcastResult,
    SendResult,
    broadcast,
    load_recipients,
    send_message,
)

logger = logging.getLogger(__name__)

API_HOST: str = "127.0.0.1"
API_PORT: int = 18790
RULES_CURRENT_PATH: str = "data/rules/current.md"
CALIBRATION_CURVE_BINS: int = 10

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

_bearer = HTTPBearer(auto_error=False)


# ---- Models ----------------------------------------------------------------


class PredictResponse(BaseModel):
    """Wire representation of a PredictionResult."""

    prediction_id: int
    ticker: str
    direction: str
    prob_up: float
    prob_up_calibrated: float | None
    confidence: float
    rationale: str
    created_at: str
    due_at: str


class OnDemandRequest(BaseModel):
    """Body for POST /stock/on_demand."""

    ticker: str = Field(min_length=1, max_length=5)
    extra_context: str | None = None


class ReportResponse(BaseModel):
    """Wire representation of ReportSummary."""

    days: int
    total_predictions: int
    scored: int
    pending: int
    hit_rate: float | None
    mean_brier: float | None
    best_call: OutcomeDetail | None
    worst_call: OutcomeDetail | None
    total_return_bps: float
    spend_usd: float


class RulesResponse(BaseModel):
    """Current rules document plus DB version metadata."""

    version: int | None
    text: str
    updated_at: str | None


class WatchlistAction(BaseModel):
    """Body for POST /stock/watchlist."""

    action: Literal["add", "remove", "list"]
    ticker: str | None = None


class WatchlistEntry(BaseModel):
    """One row of the watchlist."""

    ticker: str
    added_at: str
    active: bool


class WatchlistResponse(BaseModel):
    """Result from watchlist GET/POST endpoints."""

    tickers: list[WatchlistEntry]
    action: str
    changed: bool


class CalibrationBucket(BaseModel):
    """One bucket of the calibration curve."""

    bin_lower: float
    bin_upper: float
    mean_predicted: float
    mean_actual: float
    count: int


class CalibrationResponse(BaseModel):
    """Calibration summary plus binned curve."""

    version: int | None
    trained_at: str | None
    n_samples: int
    buckets: list[CalibrationBucket]


class ErrorResponse(BaseModel):
    """Structured error body returned by the global exception handler."""

    error: str
    detail: str | None = None


class ResearchResponse(BaseModel):
    """Wire representation of a stored research note."""

    research_id: int
    kind: str
    topic: str | None
    layer_focus: str | None
    body: str
    cost_usd: float
    created_at: str


class ResearchRunRequest(BaseModel):
    """Body for POST /stock/research."""

    layer: str | None = Field(default=None, description="Force a focus layer")
    language: str | None = Field(default=None, description="Output language override")
    push: bool = Field(default=False, description="Broadcast to WeChat recipients on success")


class DeepDiveRequest(BaseModel):
    """Body for POST /stock/deep_dive."""

    topic: str = Field(min_length=1, max_length=120)
    extra_context: str | None = None
    language: str | None = None
    push: bool = False


class ChainPlayer(BaseModel):
    """One player row inside a chain query response."""

    ticker: str
    name: str
    country: str
    role: str
    notes: str = ""


class ChainSublayer(BaseModel):
    """One sublayer inside a chain query response."""

    name: str
    function: str
    notes: str = ""
    materials: list[str]
    players: list[ChainPlayer]


class ChainLayerResponse(BaseModel):
    """Single layer dump."""

    layer: str
    function: str
    sublayers: list[ChainSublayer]


class ChainSummaryResponse(BaseModel):
    """Top-level chain summary."""

    layers: list[str]
    counts: dict[str, int]


class PushRequest(BaseModel):
    """Body for POST /stock/push."""

    recipient: str | None = Field(default=None, description="Single recipient alias; null = broadcast")
    kind: str = Field(default="daily", description="Which report kind to push")


class PushResponse(BaseModel):
    """Push outcome for one or many recipients."""

    research_id: int
    kind: str
    sent: int
    failed: int
    queued: int
    results: list[SendResult]


class DiscoverRequest(BaseModel):
    """Body for POST /stock/discover."""

    layer: str | None = None
    query: str | None = None


class DiscoverResponse(BaseModel):
    """Wire shape for a stored discovery row."""

    research_id: int
    session_label: str
    layer_focus: str
    queries: list[str]
    extraction: DiscoverExtraction
    cost_usd: float
    created_at: str


class ActionQueueRunRequest(BaseModel):
    """Body for POST /stock/action_queue/run."""

    max: int = Field(default=4, ge=1, le=20)


class ActionQueueItemModel(BaseModel):
    """Wire shape for one action_queue row."""

    id: int | None
    source_research_id: int | None
    raw_text: str
    topic: str
    status: str
    deep_dive_id: int | None
    error: str | None
    queued_at: str
    started_at: str | None
    completed_at: str | None


class ActionQueueListResponse(BaseModel):
    """Response for GET /stock/action_queue."""

    pending: list[ActionQueueItemModel]
    recent_completed: list[ActionQueueItemModel]


class ActionQueueRunResponse(BaseModel):
    """Response for POST /stock/action_queue/run."""

    drained: int
    items: list[ActionQueueItemModel]


class HoldingActionRequest(BaseModel):
    """Body for POST /stock/holdings."""

    action: Literal["add", "remove", "note"]
    ticker: str = Field(min_length=1, max_length=12)
    qty: float | None = None
    cost_basis: float | None = None
    notes: str | None = None


class HoldingModel(BaseModel):
    """Wire shape for a holdings row."""

    ticker: str
    qty: float
    cost_basis: float
    opened_at: str
    notes: str
    active: bool
    updated_at: str


class HoldingsResponse(BaseModel):
    """List of active holdings."""

    holdings: list[HoldingModel]


class AnomalyRowModel(BaseModel):
    """Wire shape for an anomaly row."""

    ticker: str
    ts: str
    pct_change: float
    volume_ratio: float
    flag_reason: str
    created_at: str


class AnomalyListResponse(BaseModel):
    """List of recent anomalies."""

    rows: list[AnomalyRowModel]


class StockHTTPException(RuntimeError):
    """Raised by handlers when a domain error should become a typed HTTP response."""

    def __init__(self, status_code: int, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail


# ---- Dependencies ----------------------------------------------------------


def get_db_conn() -> Iterator[sqlite3.Connection]:
    """Yield a per-request SQLite connection and close it on completion."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def _require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Raise 401/503 unless the bearer token matches Settings.stock_api_token."""
    # Fetch expected token from settings; 503 if ops forgot to configure it
    settings = get_settings()
    expected = settings.stock_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="STOCK_API_TOKEN not configured")

    # Reject any request without a bearer scheme
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    # Constant-time compare to avoid timing oracle even on loopback
    if not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def _validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker symbol; raise ValueError on miss."""
    normalized = ticker.upper()
    if not _TICKER_RE.match(normalized):
        raise ValueError(f"Invalid ticker '{ticker}': must be 1-5 letters")
    return normalized


# ---- Exception handlers ----------------------------------------------------


async def _stock_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Map StockHTTPException to a typed HTTP response."""
    if not isinstance(exc, StockHTTPException):
        raise exc
    body = ErrorResponse(error=exc.message, detail=exc.detail).model_dump()
    return JSONResponse(status_code=exc.status_code, content=body)


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch domain errors and otherwise return a generic 500 without leaking tracebacks."""
    # Cost ceiling reached: report Retry-After so clients can surface the budget window
    if isinstance(exc, CostCeilingError):
        body = ErrorResponse(error="cost_ceiling_reached", detail=str(exc)).model_dump()
        return JSONResponse(status_code=503, content=body, headers={"Retry-After": "3600"})

    # Value errors map to 400 (invalid ticker, missing prices/features, etc.)
    if isinstance(exc, ValueError):
        body = ErrorResponse(error="invalid_request", detail=str(exc)).model_dump()
        return JSONResponse(status_code=400, content=body)

    # Anything else is an internal error; log full traceback, reply generically
    logger.exception("Unhandled API exception on %s %s", request.method, request.url.path)
    body = ErrorResponse(error="internal_server_error").model_dump()
    return JSONResponse(status_code=500, content=body)


# ---- Handlers --------------------------------------------------------------


def health() -> dict[str, str | int]:
    """Liveness probe, no auth required."""
    return {"status": "ok", "port": API_PORT}


def get_latest_prediction(
    ticker: str, conn: sqlite3.Connection = Depends(get_db_conn)
) -> PredictResponse:
    """Return the most recent prediction stored for a ticker."""
    # Normalize + validate ticker (400 on bad input)
    normalized = _validate_ticker(ticker)

    # Pull the latest row for the ticker (id tie-breaks sub-second inserts)
    row = conn.execute(
        "SELECT id, ticker, direction, prob_up, prob_up_calibrated,"
        " confidence, rationale, created_at, due_at"
        " FROM predictions WHERE ticker = ?"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (normalized,),
    ).fetchone()
    if row is None:
        raise StockHTTPException(404, "no prediction", f"no prediction for {normalized}")

    return PredictResponse(
        prediction_id=row[0],
        ticker=row[1],
        direction=row[2],
        prob_up=row[3],
        prob_up_calibrated=row[4],
        confidence=row[5],
        rationale=row[6],
        created_at=row[7],
        due_at=row[8],
    )


def run_on_demand(
    body: OnDemandRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> PredictResponse:
    """Run a fresh prediction cycle and return the result."""
    # Validate ticker upfront so invalid input is a 400 before any work
    normalized = _validate_ticker(body.ticker)
    # extra_context is logged only; never forwarded to the LLM (news-as-data invariant)
    if body.extra_context:
        logger.info(
            "on_demand extra_context for %s: %s",
            normalized,
            body.extra_context[:120],
        )

    # Run the full predict cycle (features + LLM + DB write)
    result: PredictionResult = predict_ticker(normalized, conn)
    return PredictResponse(**result.model_dump())


def get_report(
    days: int = Query(default=7, ge=1, le=365),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> ReportResponse:
    """Aggregated hit rate / Brier / spend over the last N days."""
    summary = build_report(conn, days=days)
    return ReportResponse(**summary.model_dump())


def get_rules(conn: sqlite3.Connection = Depends(get_db_conn)) -> RulesResponse:
    """Return current rules text and the latest rules version row."""
    # Read the live rules doc from disk (empty on a fresh install)
    path = Path(RULES_CURRENT_PATH)
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""

    # Look up the latest DB row for version metadata
    row = conn.execute(
        "SELECT version, created_at FROM rules ORDER BY version DESC LIMIT 1"
    ).fetchone()
    version = row[0] if row else None
    updated_at = row[1] if row else None

    return RulesResponse(version=version, text=text, updated_at=updated_at)


def get_watchlist(
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> WatchlistResponse:
    """List all watchlist rows (active and inactive)."""
    entries = _load_watchlist(conn)
    return WatchlistResponse(tickers=entries, action="list", changed=False)


def post_watchlist(
    body: WatchlistAction, conn: sqlite3.Connection = Depends(get_db_conn)
) -> WatchlistResponse:
    """Mutate the watchlist (add / remove / list)."""
    # list action short-circuits into the GET shape
    if body.action == "list":
        entries = _load_watchlist(conn)
        return WatchlistResponse(tickers=entries, action="list", changed=False)

    # add / remove both require a ticker
    if body.ticker is None:
        raise StockHTTPException(
            400, "ticker required", f"action={body.action} needs a ticker"
        )
    normalized = _validate_ticker(body.ticker)

    # Dispatch to CRUD helpers
    if body.action == "add":
        changed = _watchlist_add(conn, normalized)
    else:
        changed = _watchlist_remove(conn, normalized)

    entries = _load_watchlist(conn)
    return WatchlistResponse(tickers=entries, action=body.action, changed=changed)


def get_research_latest(
    kind: str = Query(default="daily"),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> ResearchResponse:
    """Return the most recent stored research note."""
    if kind not in ("daily", "deep_dive"):
        raise StockHTTPException(400, "invalid kind", "kind must be 'daily' or 'deep_dive'")
    report = get_latest_report(conn, kind=kind)
    if report is None:
        raise StockHTTPException(404, "no research", f"no stored {kind} report")
    return ResearchResponse(**report.model_dump())


def post_research(
    body: ResearchRunRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> ResearchResponse:
    """Generate a fresh daily research note. Optional push=true broadcasts it."""
    report = generate_daily_research(
        conn,
        focus_layer_name=body.layer,
        language=body.language,
    )
    if body.push:
        broadcast(report.body, conn, research_id=report.research_id)
    return ResearchResponse(**report.model_dump())


def post_deep_dive(
    body: DeepDiveRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> ResearchResponse:
    """Run a topic-specific deep-dive (e.g. 'china_osat_packaging')."""
    report = generate_deep_dive(
        conn,
        topic=body.topic,
        extra_context=body.extra_context,
        language=body.language,
    )
    if body.push:
        broadcast(report.body, conn, research_id=report.research_id)
    return ResearchResponse(**report.model_dump())


def get_chain_summary() -> ChainSummaryResponse:
    """Return layer names + counts for the AI supply chain map."""
    chain = load_chain()
    return ChainSummaryResponse(
        layers=list_layer_names(chain),
        counts=chain_summary_for_log(chain),
    )


def get_chain_layer(layer: str) -> ChainLayerResponse:
    """Return the players inside a single layer."""
    chain = load_chain()
    target = chain.find_layer(layer)
    if target is None:
        raise StockHTTPException(
            404, "unknown layer", f"layer '{layer}' not in supply chain map"
        )
    sublayers = [
        ChainSublayer(
            name=sub.name,
            function=sub.function,
            notes=sub.notes,
            materials=sub.materials,
            players=[
                ChainPlayer(
                    ticker=p.ticker,
                    name=p.name,
                    country=p.country,
                    role=p.role,
                    notes=p.notes,
                )
                for p in sub.players
            ],
        )
        for sub in target.sublayers
    ]
    return ChainLayerResponse(layer=target.layer, function=target.function, sublayers=sublayers)


def post_push(
    body: PushRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> PushResponse:
    """Push the latest stored research note to one or all WeChat recipients."""
    if body.kind not in ("daily", "deep_dive"):
        raise StockHTTPException(400, "invalid kind", "kind must be 'daily' or 'deep_dive'")
    report = get_latest_report(conn, kind=body.kind)
    if report is None:
        raise StockHTTPException(404, "no research", f"no stored {body.kind} report")

    if body.recipient is None:
        result: BroadcastResult = broadcast(
            report.body, conn, research_id=report.research_id
        )
        return PushResponse(
            research_id=report.research_id,
            kind=body.kind,
            sent=result.sent,
            failed=result.failed,
            queued=result.queued,
            results=result.results,
        )

    targets = [r for r in load_recipients() if r.alias == body.recipient]
    if not targets:
        raise StockHTTPException(
            404, "unknown recipient",
            f"recipient '{body.recipient}' not in wechat_recipients.yaml",
        )

    single = send_message(
        targets[0].alias, report.body, conn, research_id=report.research_id
    )
    return PushResponse(
        research_id=report.research_id,
        kind=body.kind,
        sent=1 if single.status == "sent" else 0,
        failed=1 if single.status == "failed" else 0,
        queued=1 if single.status == "queued" else 0,
        results=[single],
    )


def post_discover(
    body: DiscoverRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> DiscoverResponse:
    """Run a web-discovery cycle (search APIs + page fetch + LLM extraction) and return it."""
    try:
        result: DiscoverResult = run_discovery(
            conn, focus_layer_name=body.layer, extra_query=body.query
        )
    except WebSearchUnavailable as exc:
        raise StockHTTPException(
            503, "web_search_unavailable", str(exc)
        )
    return DiscoverResponse(**result.model_dump())


def get_discover_latest(
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> DiscoverResponse:
    """Return the most recent stored web-discovery row."""
    result = get_latest_discovery(conn)
    if result is None:
        raise StockHTTPException(404, "no discovery", "no stored web-discovery row yet")
    return DiscoverResponse(**result.model_dump())


def get_holdings(
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> HoldingsResponse:
    """List active tracked holdings."""
    rows = holdings.list_holdings(conn, active_only=True)
    return HoldingsResponse(
        holdings=[HoldingModel(**h.model_dump()) for h in rows]
    )


def post_holdings(
    body: HoldingActionRequest, conn: sqlite3.Connection = Depends(get_db_conn)
) -> HoldingsResponse:
    """Mutate a holdings row (add / remove / note)."""
    if body.action == "add":
        if body.qty is None or body.cost_basis is None:
            raise StockHTTPException(
                400, "qty and cost_basis required",
                "add requires qty and cost_basis fields",
            )
        holdings.add_holding(
            conn, ticker=body.ticker, qty=body.qty,
            cost_basis=body.cost_basis, notes=body.notes or "",
        )
    elif body.action == "remove":
        if not holdings.remove_holding(conn, body.ticker):
            raise StockHTTPException(
                404, "ticker not found",
                f"holding {body.ticker} not present",
            )
    else:
        if body.notes is None:
            raise StockHTTPException(
                400, "note required", "note action requires notes field"
            )
        if not holdings.set_note(conn, body.ticker, body.notes):
            raise StockHTTPException(
                404, "ticker not found",
                f"holding {body.ticker} not present",
            )

    rows = holdings.list_holdings(conn, active_only=True)
    return HoldingsResponse(
        holdings=[HoldingModel(**h.model_dump()) for h in rows]
    )


def get_anomaly(
    days: int = Query(default=2, ge=1, le=14),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> AnomalyListResponse:
    """Return recent flagged anomalies."""
    rows = anomaly.recent_anomalies(conn, days=days)
    return AnomalyListResponse(
        rows=[
            AnomalyRowModel(
                ticker=r.ticker, ts=r.ts, pct_change=r.pct_change,
                volume_ratio=r.volume_ratio, flag_reason=r.flag_reason,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


def get_action_queue(
    status: str = Query(default="all"),
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> ActionQueueListResponse:
    """List pending + recently-completed action_queue rows."""
    if status not in ("all", "pending", "done"):
        raise StockHTTPException(400, "invalid status", "status must be all/pending/done")

    pending = (
        action_queue.pending_items(conn)
        if status in ("all", "pending") else []
    )
    completed = (
        action_queue.recent_completed(conn, hours=24)
        if status in ("all", "done") else []
    )
    return ActionQueueListResponse(
        pending=[ActionQueueItemModel(**item.model_dump()) for item in pending],
        recent_completed=[
            ActionQueueItemModel(**item.model_dump()) for item in completed
        ],
    )


def post_action_queue_run(
    body: ActionQueueRunRequest,
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> ActionQueueRunResponse:
    """Drain up to body.max pending action_queue rows synchronously."""
    completed = action_queue.run_pending(conn, max_items=body.max)
    return ActionQueueRunResponse(
        drained=len(completed),
        items=[ActionQueueItemModel(**item.model_dump()) for item in completed],
    )


def get_calibration(
    conn: sqlite3.Connection = Depends(get_db_conn),
) -> CalibrationResponse:
    """Return the calibration curve over the last 500 scored predictions."""
    # Latest calibration row provides version/trained_at metadata
    meta = conn.execute(
        "SELECT version, trained_at FROM calibration ORDER BY version DESC LIMIT 1"
    ).fetchone()

    # Pull (prob_up, direction_hit) pairs joining predictions to outcomes
    rows = conn.execute(
        "SELECT p.prob_up, o.direction_hit"
        " FROM predictions p JOIN outcomes o ON p.id = o.prediction_id"
        " ORDER BY p.created_at DESC LIMIT 500"
    ).fetchall()

    # Bucket into equal-width probability bins
    buckets = _bucket_calibration(
        [(float(r[0]), int(r[1])) for r in rows], bins=CALIBRATION_CURVE_BINS
    )
    return CalibrationResponse(
        version=meta[0] if meta else None,
        trained_at=meta[1] if meta else None,
        n_samples=len(rows),
        buckets=buckets,
    )


# ---- Helpers ---------------------------------------------------------------


def _load_watchlist(conn: sqlite3.Connection) -> list[WatchlistEntry]:
    """Return every row of the watchlist table as a pydantic model."""
    rows = conn.execute(
        "SELECT ticker, added_at, active FROM watchlist ORDER BY ticker"
    ).fetchall()
    return [
        WatchlistEntry(ticker=row[0], added_at=row[1], active=bool(row[2]))
        for row in rows
    ]


def _watchlist_add(conn: sqlite3.Connection, ticker: str) -> bool:
    """Insert or re-activate a ticker; return True if the row changed."""
    # Look up existing row for idempotency decisions
    existing = conn.execute(
        "SELECT active FROM watchlist WHERE ticker = ?", (ticker,)
    ).fetchone()

    now = datetime.now(timezone.utc).isoformat()
    if existing is None:
        conn.execute(
            "INSERT INTO watchlist (ticker, added_at, active) VALUES (?, ?, 1)",
            (ticker, now),
        )
        conn.commit()
        return True

    # Already active: nothing to change
    if existing[0] == 1:
        return False

    # Re-activate and refresh added_at for the audit trail
    conn.execute(
        "UPDATE watchlist SET active = 1, added_at = ? WHERE ticker = ?",
        (now, ticker),
    )
    conn.commit()
    return True


def _watchlist_remove(conn: sqlite3.Connection, ticker: str) -> bool:
    """Set active=0 for a ticker; return True if any row was updated."""
    # Surface 404 when caller removes a ticker that never existed
    existing = conn.execute(
        "SELECT active FROM watchlist WHERE ticker = ?", (ticker,)
    ).fetchone()
    if existing is None:
        raise StockHTTPException(
            404, "ticker not found", f"ticker {ticker} is not on the watchlist"
        )

    # Already inactive: idempotent no-op
    if existing[0] == 0:
        return False

    conn.execute("UPDATE watchlist SET active = 0 WHERE ticker = ?", (ticker,))
    conn.commit()
    return True


def _bucket_calibration(
    rows: list[tuple[float, int]], bins: int
) -> list[CalibrationBucket]:
    """Group (prob_up, direction_hit) pairs into equal-width probability bins."""
    if not rows or bins <= 0:
        return []

    # Initialize accumulators for each bin
    width = 1.0 / bins
    sums_prob: list[float] = [0.0] * bins
    sums_hit: list[float] = [0.0] * bins
    counts: list[int] = [0] * bins

    # Assign each (prob, hit) pair to its bucket (top edge snaps into last bin)
    for prob, hit in rows:
        clamped = max(0.0, min(1.0, prob))
        idx = int(clamped / width)
        if idx >= bins:
            idx = bins - 1
        sums_prob[idx] += clamped
        sums_hit[idx] += hit
        counts[idx] += 1

    # Emit only non-empty buckets, sorted ascending by bin_lower
    buckets: list[CalibrationBucket] = []
    for i in range(bins):
        if counts[i] == 0:
            continue
        buckets.append(
            CalibrationBucket(
                bin_lower=round(i * width, 4),
                bin_upper=round((i + 1) * width, 4),
                mean_predicted=round(sums_prob[i] / counts[i], 4),
                mean_actual=round(sums_hit[i] / counts[i], 4),
                count=counts[i],
            )
        )
    return buckets


# ---- App factory -----------------------------------------------------------


def create_app() -> FastAPI:
    """Build the FastAPI app with all routes and handlers registered."""
    api = FastAPI(title="stock", version="0.1.0")

    # Log policy: silence successful GETs (polls / health / reads), log every
    # POST/PUT/DELETE (writes -- boss replies, syncs, mutations are interesting),
    # and log every failure (>=400) regardless of method.
    @api.middleware("http")
    async def _log_writes_and_failures(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        is_failure = response.status_code >= 400
        is_write = request.method in ("POST", "PUT", "DELETE", "PATCH")
        if is_failure:
            logger.warning(
                "%s %s -> %d",
                request.method, request.url.path, response.status_code,
            )
        elif is_write:
            logger.info(
                "%s %s -> %d",
                request.method, request.url.path, response.status_code,
            )
        return response

    # Custom exception handlers (domain + fallthrough)
    api.add_exception_handler(StockHTTPException, _stock_exception_handler)
    api.add_exception_handler(CostCeilingError, _unhandled_exception_handler)
    api.add_exception_handler(ValueError, _unhandled_exception_handler)
    api.add_exception_handler(Exception, _unhandled_exception_handler)

    # Public liveness probe — no auth
    api.add_api_route(
        "/stock/health",
        health,
        methods=["GET"],
        response_model=None,
    )

    # Protected routes: bearer auth via _require_token
    protected_deps = [Depends(_require_token)]
    api.add_api_route(
        "/stock/predict/{ticker}",
        get_latest_prediction,
        methods=["GET"],
        response_model=PredictResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/on_demand",
        run_on_demand,
        methods=["POST"],
        response_model=PredictResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/report",
        get_report,
        methods=["GET"],
        response_model=ReportResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/rules",
        get_rules,
        methods=["GET"],
        response_model=RulesResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/watchlist",
        get_watchlist,
        methods=["GET"],
        response_model=WatchlistResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/watchlist",
        post_watchlist,
        methods=["POST"],
        response_model=WatchlistResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/calibration",
        get_calibration,
        methods=["GET"],
        response_model=CalibrationResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/research/latest",
        get_research_latest,
        methods=["GET"],
        response_model=ResearchResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/research",
        post_research,
        methods=["POST"],
        response_model=ResearchResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/deep_dive",
        post_deep_dive,
        methods=["POST"],
        response_model=ResearchResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/chain",
        get_chain_summary,
        methods=["GET"],
        response_model=ChainSummaryResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/chain/{layer}",
        get_chain_layer,
        methods=["GET"],
        response_model=ChainLayerResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/push",
        post_push,
        methods=["POST"],
        response_model=PushResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/discover",
        post_discover,
        methods=["POST"],
        response_model=DiscoverResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/discover/latest",
        get_discover_latest,
        methods=["GET"],
        response_model=DiscoverResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/action_queue",
        get_action_queue,
        methods=["GET"],
        response_model=ActionQueueListResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/action_queue/run",
        post_action_queue_run,
        methods=["POST"],
        response_model=ActionQueueRunResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/holdings",
        get_holdings,
        methods=["GET"],
        response_model=HoldingsResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/holdings",
        post_holdings,
        methods=["POST"],
        response_model=HoldingsResponse,
        dependencies=protected_deps,
    )
    api.add_api_route(
        "/stock/anomaly",
        get_anomaly,
        methods=["GET"],
        response_model=AnomalyListResponse,
        dependencies=protected_deps,
    )

    # Boss-facing dashboard + channel API at /channel/* (per-recipient bearer tokens,
    # separate auth boundary from the admin /stock/* routes).
    api.include_router(create_channel_router())
    api.add_exception_handler(ChannelHTTPError, channel_exception_handler)

    # Sync endpoints at /sync/* -- only used by the local laptop pushing to a
    # Render-hosted cloud_proxy instance. Same admin-token auth as /stock/*.
    api.include_router(create_sync_router())

    return api


app = create_app()


# ---- Entry point -----------------------------------------------------------


def run_api() -> None:
    """Run the FastAPI app (blocking).

    Binds to API_HOST/API_PORT by default. Render injects PORT and expects 0.0.0.0;
    if PORT is set in env, override accordingly.
    """
    import os

    host = "0.0.0.0" if os.environ.get("PORT") else API_HOST
    port = int(os.environ.get("PORT", API_PORT))
    uvicorn.run(
        "stock.api:app",
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
