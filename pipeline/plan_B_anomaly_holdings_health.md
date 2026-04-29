# Plan B — F12: Anomaly flagger + Holdings tracker + Health-check deep-dive

Three composable sub-features that layer real market signal onto the existing
OHLCV ingest. After this lands, the daily note opens with concrete numbers
(volume spikes, hit positions) instead of pure narrative.

## Sub-feature breakdown

### 1. Anomaly flagger
Compute today's anomalies per ticker from the existing `prices` table; surface
in the research prompt as "异常波动 / Anomalies".

### 2. Holdings tracker
New YAML-backed table for tracked positions; CLI to mutate it; surfaces in the
research prompt as "组合 / Holdings".

### 3. Weekly health-check deep-dive + Form 4 insider fetcher
Per-holding deep-dive every Saturday with extra context (anomalies + Form 4 +
news features). New SEC EDGAR Form 4 module pulls the last N transactions per
ticker on the watchlist.

## File changes table

| File                                | Change | What                                                              |
|-------------------------------------|--------|-------------------------------------------------------------------|
| `src/stock/db.py`                   | edit   | New `holdings`, `insider_filings`, `price_anomalies` tables       |
| `src/stock/anomaly.py`              | new    | `compute_daily_anomalies(conn)`, `format_anomaly_block()`         |
| `src/stock/holdings.py`             | new    | YAML <-> DB sync, CRUD helpers, `format_holdings_block()`         |
| `src/stock/ingest/insiders.py`      | new    | EDGAR Form 4 fetcher; ATOM feed parse; persist last N             |
| `data/holdings.yaml`                | new    | `{tickers: [{ticker, qty, cost_basis, opened_at, notes}]}`        |
| `src/stock/research.py`             | edit   | New `_build_anomaly_block`, `_build_holdings_block`; format-args  |
| `src/stock/cli.py`                  | edit   | `stock holding add/remove/list/note`; `stock anomaly run`         |
| `src/stock/api.py`                  | edit   | `GET /stock/anomaly`, `GET/POST /stock/holdings`, `GET /stock/insiders/{ticker}` |
| `src/stock/orchestrator.py`         | edit   | New `_job_compute_anomalies`, `_job_health_check`, `_job_pull_insiders` |
| `prompts/research.txt`              | edit   | New "异常波动" section between "今日主线" and "重点跟踪"; new "组合 / Holdings" section |
| `prompts/health_check.txt`          | new    | Deep-dive variant for the health-check job                        |
| `openclaw_skill/stock.skill.md`     | edit   | Document `stock.holdings`, `stock.anomaly`, `stock.insiders`      |
| `docs/code_structure.md`            | edit   | Append three new modules + three new tables                       |
| `tests/test_anomaly.py`             | new    | Synthetic OHLCV → expected flags                                  |
| `tests/test_holdings.py`            | new    | YAML sync, idempotent add, remove, note                           |
| `tests/test_ingest_insiders.py`     | new    | Mocked EDGAR ATOM responses                                       |
| `tests/test_research.py`            | edit   | Cover new prompt blocks                                           |

## Schema additions (`src/stock/db.py`)

```sql
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
    form_type TEXT NOT NULL,            -- "4" | "4/A"
    filed_at TEXT NOT NULL,
    transaction_type TEXT,              -- buy / sell / grant
    shares REAL,
    price REAL,
    accession_number TEXT NOT NULL UNIQUE,
    raw_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_insider_filings_ticker ON insider_filings (ticker, filed_at DESC);

CREATE TABLE IF NOT EXISTS price_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    ts TEXT NOT NULL,                   -- yyyy-mm-dd
    pct_change REAL NOT NULL,
    volume_ratio REAL NOT NULL,         -- today_v / 30d_avg_v
    flag_reason TEXT NOT NULL,          -- "volume_spike" | "price_move" | "both"
    created_at TEXT NOT NULL,
    UNIQUE(ticker, ts)
);
CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON price_anomalies (ts DESC);
```

## `src/stock/anomaly.py` shape

Module docstring: `"""stock.anomaly -- detect daily volume/price anomalies on watchlist + holdings."""`

Constants: `VOLUME_RATIO_THRESHOLD = 1.5`, `PCT_CHANGE_THRESHOLD = 0.05`,
`AVG_WINDOW_DAYS = 30`, `MAX_FLAGGED_PER_DAY = 25`.

Public surface:

- `class AnomalyRow(BaseModel)` — wraps one detected row.
- `compute_daily_anomalies(conn) -> list[AnomalyRow]` — for each ticker
  appearing in `prices` *and* (`watchlist` ∪ `holdings`):
  1. Latest bar = `MAX(ts)` row.
  2. 30-day avg volume = average over last 30 trading days excluding latest.
  3. `pct_change = (c_today - c_yesterday) / c_yesterday`.
  4. `volume_ratio = v_today / avg_volume`.
  5. Flag when `volume_ratio >= 1.5` or `abs(pct_change) >= 0.05`.
  6. UPSERT into `price_anomalies` (idempotent on `(ticker, ts)`).
- `recent_anomalies(conn, *, days=2) -> list[AnomalyRow]` — last 2-day cutoff.
- `format_anomaly_block(rows) -> str` — markdown-ish bullet block for the prompt.

## `src/stock/holdings.py` shape

Module docstring: `"""stock.holdings -- portfolio tracker fed by data/holdings.yaml + DB."""`

Public surface:

- `class Holding(BaseModel)` — `ticker`, `qty`, `cost_basis`, `opened_at`,
  `notes`, `active`, `updated_at`.
- `sync_from_yaml(conn, path: str = HOLDINGS_PATH) -> int` — read YAML,
  upsert each row, mark missing tickers `active=0`. Called on startup
  from `orchestrator.run_orchestrator` and from the API/CLI on add/remove.
- `add_holding(conn, *, ticker, qty, cost_basis, notes="")` — idempotent.
- `remove_holding(conn, ticker)` — sets `active=0`.
- `list_holdings(conn, *, active_only=True) -> list[Holding]`.
- `set_note(conn, ticker, note: str)`.
- `format_holdings_block(rows) -> str` — for prompt injection. Includes
  ticker, qty, cost basis, "% from cost" (if latest price exists), notes.

`data/holdings.yaml` sample:
```yaml
holdings:
  - ticker: NVDA
    qty: 100
    cost_basis: 480.00
    opened_at: "2025-12-01"
    notes: "core AI compute exposure"
```

## `src/stock/ingest/insiders.py` shape

Module docstring: `"""stock.ingest.insiders -- pull SEC EDGAR Form 4 insider filings (free, no key)."""`

EDGAR endpoint:
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10&output=atom`

Required header: `User-Agent: <project> <contact-email>` per EDGAR policy
(use a configurable default; warn at startup if unset).

Public surface:

- `class InsiderTransaction(BaseModel)` — `ticker`, `filer_name`, `filer_role`,
  `form_type`, `filed_at`, `transaction_type`, `shares`, `price`,
  `accession_number`, `raw_url`.
- `lookup_cik(ticker: str) -> str | None` — uses
  `https://www.sec.gov/files/company_tickers.json` cached locally for 7d.
- `fetch_form4(ticker, *, limit=10) -> list[InsiderTransaction]` —
  ATOM parse; per-entry, fetch the primary doc (also XML), extract
  `transactionShares`, `transactionPricePerShare`, `transactionCode`.
  Skip non-4 / amended-only entries via `form_type` filter.
- `persist_insiders(conn, ticker) -> int` — UPSERT on `accession_number`.
- `recent_for_ticker(conn, ticker, *, days=90) -> list[InsiderTransaction]`.

Network etiquette: 100ms sleep between requests, max 10 entries per ticker
per run, retry-after honored. Ten tickers × 10ms is well under SEC's 10/sec
budget.

Settings additions in `config.py`:
- `edgar_user_agent: str = "stock-research 0.1 ops@example.com"` (warn at
  startup if it still says `example.com`).

## Research prompt edits

Two new sections added between "今日主线" (1) and "重点跟踪" (2):

> 1.5 **异常波动 / Anomalies (last 24h)**
> {anomaly_block}
>
> 1.7 **组合 / Current holdings**
> {holdings_block}

Holdings block lists ticker, qty, P&L %, latest anomaly flag, latest insider
filing summary if any in last 30 days. The deep-dive prompt is unchanged for
F12 sub-features 1+2; sub-feature 3 introduces a new prompt below.

## New prompt: `prompts/health_check.txt`

A specialized deep-dive prompt that injects:
- All anomalies for the holding in the last 14 days.
- Form 4 transactions in the last 90 days.
- Top 5 news features by sentiment magnitude in last 14 days.
- Cost basis + holding period from `holdings.notes`.

Output structure: 健康度评分 (1-5) | 主要风险 | 仓位建议 (持有/减仓/加仓) |
催化剂时间表. Renders one note per holding; orchestrator concatenates and
sends a single "组合健康度" message.

## CLI / API additions

CLI:
- `stock holding add TICKER QTY COST_BASIS [--notes "..."]`
- `stock holding remove TICKER`
- `stock holding list`
- `stock holding note TICKER "free text"`
- `stock anomaly run` — recompute now and print flagged rows.
- `stock insiders pull TICKER` — refresh Form 4 cache for one ticker.
- `stock health-check [--push]` — run the weekly health-check job manually.

API:
- `GET /stock/anomaly?days=2` → `[AnomalyRow]`
- `GET /stock/holdings` / `POST /stock/holdings` (action add/remove/note)
- `GET /stock/insiders/{ticker}?days=90`
- `POST /stock/health_check` body `{push: bool}` — sync run.

Skill manifest adds three tools.

## Scheduler updates

Add three jobs to `orchestrator.create_scheduler()`:

```python
# Daily anomaly recompute right after the close-scoring job
scheduler.add_job(
    _job_compute_anomalies,
    CronTrigger(hour=SCORE_HOUR, minute=SCORE_MINUTE + 5,
                day_of_week="mon-fri", timezone="UTC"),
    id="anomaly_compute",
    name="Daily price/volume anomaly computation",
)
# Weekly insider pull on every watchlist + holdings ticker
scheduler.add_job(
    _job_pull_insiders,
    CronTrigger(hour=5, minute=0, day_of_week="sun", timezone="UTC"),
    id="insiders_pull",
    name="Weekly EDGAR Form 4 pull",
)
# Health check: every Saturday 07:00 UTC (after weekly reflection at 06:00)
scheduler.add_job(
    _job_health_check,
    CronTrigger(hour=7, minute=0, day_of_week="sat", timezone="UTC"),
    id="health_check_weekly",
    name="Per-holding weekly health-check deep-dive",
)
```

`_job_health_check` iterates `list_holdings(conn, active_only=True)` and
calls `generate_deep_dive(conn, topic=ticker, extra_context=...)` with a
context block built from anomalies+filings+news. Concatenates each report
into one "组合健康度" body (with H2 per ticker), broadcasts.

## Time estimate

- Session 1 (~3h): anomaly module + tests + prompt section.
- Session 2 (~3h): holdings module + YAML sync + CLI + API + tests.
- Session 3 (~3h): insiders module + EDGAR cache + health-check job +
  prompt + scheduler + tests.

Total: ~9h, 3 sessions.

## Test plan

- `test_anomaly.py`:
  - Synthetic price ladder where day N has 2x volume → flag triggers.
  - 4% pct change without volume spike → no flag.
  - Idempotent UPSERT on rerun (same ts → one row).
  - `format_anomaly_block` empty case returns the "no anomalies" string.
- `test_holdings.py`:
  - `sync_from_yaml` adds three, removes one, notes preserved on resync.
  - `add_holding` idempotent on same `(ticker, qty, cost_basis)`.
  - `format_holdings_block` shows P&L when latest price exists, "N/A" else.
- `test_ingest_insiders.py`:
  - Mocked ATOM feed → 3 entries parsed; one is form 4/A → still kept.
  - `lookup_cik` honors local cache.
  - UA header asserted in mocked request.
  - Persist is UPSERT on `accession_number`.
- `test_research.py` extension: anomaly + holdings blocks present in
  rendered prompt; ordering between sections preserved.
- `test_orchestrator.py` extension: three new jobs registered; their
  `id`s appear in `get_schedule_info`.

## Risks / mitigations

- **EDGAR rate limit / outage** → fetcher returns empty list and logs;
  health-check still runs with anomalies+news only.
- **YAML drift vs DB** → `sync_from_yaml` is the single source of truth;
  CLI/API mutations write *both* to DB and back to YAML (with a
  best-effort lock — single-writer assumption holds on this laptop).
- **Form 4 entries without price/shares** (e.g. grants) → store NULLs;
  prompt formatter labels them as "grant/exercise".
- **Anomaly false positives on illiquid tickers** → require
  `avg_volume > 50_000`; below that, skip flagging.
