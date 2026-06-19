"""stock.db -- SQLite connection factory and schema creation."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import sqlite_vec

from stock.config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    embedding BLOB
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    ts TEXT NOT NULL,
    o REAL NOT NULL,
    h REAL NOT NULL,
    l REAL NOT NULL,
    c REAL NOT NULL,
    v INTEGER NOT NULL,
    PRIMARY KEY (ticker, ts)
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL REFERENCES news(id),
    json TEXT NOT NULL,
    model TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    direction TEXT NOT NULL,
    prob_up REAL NOT NULL,
    prob_up_calibrated REAL,
    expected_return_bps REAL,
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL,
    key_factors_json TEXT NOT NULL,
    model_used TEXT NOT NULL,
    strategy_arm TEXT,
    rules_version INTEGER,
    retrieved_case_ids TEXT,
    created_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    feature_context_json TEXT
);

CREATE TABLE IF NOT EXISTS outcomes (
    prediction_id INTEGER PRIMARY KEY REFERENCES predictions(id),
    actual_return REAL NOT NULL,
    direction_hit INTEGER NOT NULL,
    brier REAL NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    version INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    reflection_input_ids TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bandit_state (
    strategy_arm TEXT NOT NULL,
    ticker_bucket TEXT NOT NULL,
    alpha REAL NOT NULL DEFAULT 1.0,
    beta REAL NOT NULL DEFAULT 1.0,
    pulls INTEGER NOT NULL DEFAULT 0,
    reward_sum REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy_arm, ticker_bucket)
);

CREATE TABLE IF NOT EXISTS calibration (
    version INTEGER PRIMARY KEY,
    params BLOB NOT NULL,
    trained_on_ids TEXT,
    trained_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    duration_ms INTEGER NOT NULL,
    caller TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    topic TEXT,
    layer_focus TEXT,
    body TEXT NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    -- CN/US 双轨: which report track a 'daily' note belongs to ('CN' A/H China,
    -- 'US' US-listed). NULL for legacy single-track notes and non-daily kinds
    -- (reply/feature_request/deep_dive). History/grading is NOT partitioned by
    -- this -- it only separates the two forward-looking daily pushes.
    track TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wechat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    research_id INTEGER REFERENCES research_reports(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_label TEXT NOT NULL,
    layer_focus TEXT,
    queries_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_research_id INTEGER REFERENCES research_reports(id),
    raw_text TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    deep_dive_id INTEGER REFERENCES research_reports(id),
    error TEXT,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    ticker TEXT PRIMARY KEY,
    qty REAL NOT NULL,
    cost_basis REAL NOT NULL,
    opened_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insider_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    filer_name TEXT NOT NULL,
    filer_role TEXT,
    form_type TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    transaction_type TEXT,
    shares REAL,
    price REAL,
    accession_number TEXT NOT NULL UNIQUE,
    raw_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    ts TEXT NOT NULL,
    pct_change REAL NOT NULL,
    volume_ratio REAL NOT NULL,
    flag_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(ticker, ts)
);

CREATE TABLE IF NOT EXISTS tech_dive_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    sector TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'zh',
    research_id INTEGER REFERENCES research_reports(id),
    rounds INTEGER NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    -- Chokepoint 5-dim research-priority score (boss "Serenity" directive).
    -- Nullable: a dive that omits the SCORES line still persists with NULLs.
    phase TEXT,
    score_trend INTEGER,
    score_bottleneck INTEGER,
    score_validation INTEGER,
    score_valuation INTEGER,
    score_risk INTEGER,
    score_composite REAL
);

CREATE TABLE IF NOT EXISTS ai_loop_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    quarterly_revenue_usd REAL,
    quarterly_revenue_yoy REAL,
    revenue_yoy_4q_mean REAL,
    revenue_decel REAL,
    gross_margin REAL,
    gross_margin_4q_mean REAL,
    margin_compression REAL,
    risk_flag TEXT NOT NULL,
    UNIQUE(ticker, measured_at)
);

CREATE TABLE IF NOT EXISTS smallcap_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    sector TEXT NOT NULL,
    market_cap_usd REAL,
    revenue_inflection REAL,
    news_sparsity_score REAL,
    score REAL NOT NULL,
    niche_bottleneck TEXT NOT NULL,
    inflection_signal TEXT,
    flag_reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(ticker, detected_at)
);

CREATE TABLE IF NOT EXISTS option_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    contract_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    volume INTEGER NOT NULL,
    open_interest INTEGER NOT NULL,
    vol_oi_ratio REAL NOT NULL,
    implied_vol REAL,
    underlying_price REAL,
    distance_pct REAL,
    score REAL NOT NULL,
    flag_reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(contract_symbol, detected_at)
);

CREATE TABLE IF NOT EXISTS option_ratio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    call_volume INTEGER NOT NULL,
    put_volume INTEGER NOT NULL,
    call_open_interest INTEGER NOT NULL,
    put_open_interest INTEGER NOT NULL,
    call_put_volume_ratio REAL,
    put_call_volume_ratio REAL,
    call_put_oi_ratio REAL,
    put_call_oi_ratio REAL,
    expiries_scanned INTEGER NOT NULL,
    contracts_scanned INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(ticker, detected_at)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    direction TEXT NOT NULL,
    body TEXT NOT NULL,
    intent TEXT,
    intent_confidence REAL,
    related_research_id INTEGER REFERENCES research_reports(id),
    related_action_queue_id INTEGER REFERENCES action_queue(id),
    rewrite_id INTEGER,
    created_at TEXT NOT NULL,
    embedding_idx INTEGER
);

CREATE TABLE IF NOT EXISTS prompt_rewrites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_path TEXT NOT NULL,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    rationale TEXT NOT NULL,
    triggered_by_conversation_id INTEGER REFERENCES conversations(id),
    cost_usd REAL NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_ticker_url ON news (ticker, url);
CREATE INDEX IF NOT EXISTS idx_research_kind_created ON research_reports (kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wechat_log_created ON wechat_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_research_created ON web_research (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_queue_status ON action_queue (status, queued_at);
CREATE INDEX IF NOT EXISTS idx_action_queue_source ON action_queue (source_research_id);
CREATE INDEX IF NOT EXISTS idx_insider_filings_ticker ON insider_filings (ticker, filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON price_anomalies (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ai_loop_measured
    ON ai_loop_health (measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_smallcap_score
    ON smallcap_candidates (detected_at DESC, score DESC);
CREATE INDEX IF NOT EXISTS idx_smallcap_sector
    ON smallcap_candidates (sector, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_option_anom_ticker_detected
    ON option_anomalies (ticker, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_option_anom_score
    ON option_anomalies (detected_at DESC, score DESC);
CREATE INDEX IF NOT EXISTS idx_option_ratio_ticker_detected
    ON option_ratio_snapshots (ticker, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_option_ratio_detected
    ON option_ratio_snapshots (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_recipient_created
    ON conversations (recipient, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_intent
    ON conversations (intent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_rewrites_applied
    ON prompt_rewrites (applied, created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS case_embeddings USING vec0(
    prediction_id INTEGER PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_embeddings USING vec0(
    conversation_id INTEGER PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_embeddings USING vec0(
    research_id INTEGER PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);

CREATE TABLE IF NOT EXISTS recipient_tokens (
    token TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recipient_tokens_recipient ON recipient_tokens (recipient);

CREATE TABLE IF NOT EXISTS cloud_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'pending',
    actual_outcome TEXT,
    evidence_text TEXT,
    evidence_source TEXT,
    evidence_url TEXT,
    source_research_id INTEGER REFERENCES research_reports(id),
    verdict_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracked_events_status
    ON tracked_events (status, window_end);
CREATE INDEX IF NOT EXISTS idx_tracked_events_ticker
    ON tracked_events (ticker, status);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    score REAL NOT NULL,
    components_json TEXT NOT NULL,
    qap_gate INTEGER NOT NULL DEFAULT 0,
    first_flagged_at TEXT NOT NULL,
    last_score_at TEXT NOT NULL,
    last_score REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    promoted_at TEXT,
    dismissed_at TEXT,
    notes TEXT,
    UNIQUE(ticker)
);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_score
    ON discovery_candidates (status, score DESC);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_last_score
    ON discovery_candidates (last_score_at DESC);

CREATE TABLE IF NOT EXISTS prediction_theses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL REFERENCES predictions(id),
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    verifiable_by TEXT,
    chain_consistency TEXT,
    chain_consistency_reason TEXT,
    verdict TEXT,
    confidence REAL,
    evidence_text TEXT,
    evidence_source TEXT,
    graded_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prediction_theses_pred
    ON prediction_theses (prediction_id);
CREATE INDEX IF NOT EXISTS idx_prediction_theses_verdict
    ON prediction_theses (verdict, graded_at DESC);

CREATE TABLE IF NOT EXISTS self_review_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_date TEXT NOT NULL,
    backend TEXT NOT NULL,
    title TEXT NOT NULL,
    rationale TEXT NOT NULL,
    files_json TEXT NOT NULL,
    diff_or_steps TEXT NOT NULL,
    impact TEXT,
    risk TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_self_review_date
    ON self_review_proposals (review_date DESC);
CREATE INDEX IF NOT EXISTS idx_self_review_applied
    ON self_review_proposals (applied, created_at DESC);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    started_at TEXT,
    finished_at TEXT NOT NULL,
    duration_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_runs_job
    ON job_runs (job_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_runs_status
    ON job_runs (status, finished_at DESC);

CREATE TABLE IF NOT EXISTS usage_limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    caller TEXT NOT NULL,
    detail TEXT,
    detected_at TEXT NOT NULL,
    retried_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_limit_events_time
    ON usage_limit_events (detected_at DESC);

CREATE TABLE IF NOT EXISTS gov_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    politician TEXT NOT NULL,
    chamber TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    amount_range TEXT NOT NULL DEFAULT '',
    transaction_date TEXT NOT NULL,
    disclosed_at TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    ingested_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gov_trades_dedup
    ON gov_trades (politician, ticker, transaction_type, transaction_date, amount_range);
CREATE INDEX IF NOT EXISTS idx_gov_trades_ticker
    ON gov_trades (ticker, transaction_date DESC);

CREATE TABLE IF NOT EXISTS signal_ablation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal TEXT NOT NULL,
    delta_pp REAL,
    n_with INTEGER NOT NULL DEFAULT 0,
    n_without INTEGER NOT NULL DEFAULT 0,
    actionable INTEGER NOT NULL DEFAULT 0,
    verdict TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_ablation_sig
    ON signal_ablation (signal, recorded_at DESC);

CREATE TABLE IF NOT EXISTS context_nodes (
    node TEXT NOT NULL,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    token_estimate INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (node, scope)
);
"""


# Columns added to existing tables after their initial ship date. CREATE TABLE
# IF NOT EXISTS never alters a live table, so we add any missing column here.
# Format: table -> [(column, sql_type), ...]. Idempotent and logged.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "tech_dive_runs": [
        ("phase", "TEXT"),
        ("score_trend", "INTEGER"),
        ("score_bottleneck", "INTEGER"),
        ("score_validation", "INTEGER"),
        ("score_valuation", "INTEGER"),
        ("score_risk", "INTEGER"),
        ("score_composite", "REAL"),
    ],
    # Calibration guard: a fitted model is only APPLIED when it beat raw Brier on
    # a holdout (helps=1). brier_raw/brier_cal record the validation result.
    "calibration": [
        ("helps", "INTEGER DEFAULT 0"),
        ("brier_raw", "REAL"),
        ("brier_cal", "REAL"),
    ],
    # Failed-item retry (2026-06-12): deep dives killed by transient CLI
    # failures are re-queued at the next drain instead of dying silently.
    "action_queue": [
        ("attempts", "INTEGER DEFAULT 0"),
    ],
    # CN/US 双轨 (2026-06-17): tag each daily note with its report track so the
    # dashboard/APK can show the China and US pushes separately.
    "research_reports": [
        ("track", "TEXT"),
    ],
}


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they do not exist, then backfill new columns."""
    conn.executescript(_SCHEMA_SQL)

    # Backfill columns added to pre-existing tables in live databases.
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in columns:
            if name in existing:
                continue
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
            except sqlite3.OperationalError as exc:
                logger.warning("ALTER TABLE %s ADD COLUMN %s failed: %s", table, name, exc)
    conn.commit()


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and foreign keys enabled.

    If db_path is None, reads from Settings. Pass ":memory:" for tests.

    check_same_thread=False is REQUIRED for FastAPI's async endpoints: when an
    `async def` handler awaits a non-async I/O call (e.g. `await image.read()`
    on a multipart upload), the coroutine may resume on a different worker
    thread than the one that called the dependency that opened this conn.
    Without this flag, every post-await DB access on the original conn raises
    'SQLite objects created in a thread can only be used in that same thread.'
    Each request still gets its own conn (FastAPI dependency lifecycle), so
    we don't expose ourselves to the usual concurrency hazard this flag warns
    about; the request handler is the only writer.
    """
    if db_path is None:
        db_path = get_settings().db_path

    # Ensure parent directory exists for file-based databases
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")

    # Load sqlite-vec extension for vector search
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # WAL mode is ignored for :memory: databases
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        # WAL alone permits concurrent readers during a write but still
        # serializes writers. Without busy_timeout, a second writer raises
        # `database is locked` immediately. Codex/claude_cli core calls can
        # take 10-30s each and hold the connection open; during a fan-out
        # ingest cycle (~26 tickers concurrent) the 5s ceiling we shipped
        # initially burst-failed 30 writes in 4 min. 30s comfortably absorbs
        # the worst-case codex round-trip while staying short enough to
        # surface a truly stuck writer.
        conn.execute("PRAGMA busy_timeout = 30000")

    _ensure_schema(conn)
    return conn
