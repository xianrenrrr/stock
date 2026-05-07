# Code structure (living doc)

Per boss instruction 2026-05-06: maintained on every commit so the project
state is always inspectable from one document. If a feature lands without
a corresponding entry here, the commit is incomplete.

Last updated: 2026-05-07 evening (F44 analyst skills + company DD queue + 4.5h cron + entry-zone tool)

---

## Top-level layout

```
STOCK/
├── src/stock/                 production code
├── data/                      curated YAML inputs (editable in any editor)
├── prompts/                   LLM prompt templates
├── tests/                     pytest suite (mocks all I/O)
├── pipeline/                  generated reports + logs (git-ignored except plan_*)
├── apk/                       Android client (separate build chain)
├── render/                    Render-deployed cloud_proxy mode config
├── scripts/                   one-shot ops (install_service.ps1 etc.)
└── code_structure.md          THIS FILE
```

## src/stock/ -- production modules

Grouped by responsibility:

### Core / entrypoints
| Module | Role |
|---|---|
| `cli.py` | Typer CLI -- entrypoint for all manual operations |
| `orchestrator.py` | APScheduler runner for ~24 cron jobs |
| `api.py` | FastAPI server (Render cloud_proxy mode + local serve) |
| `config.py` | pydantic Settings -- all env vars |
| `db.py` | sqlite3 connection factory + WAL schema |
| `models.py` | LLM client abstraction; `get_core_client()` routes everything |

### LLM-touching feature modules (all flow through `get_core_client`)
| Module | Feature | Frequency |
|---|---|---|
| `research.py` | Daily research note generator (F00) | 2x/day |
| `predict.py` | Per-ticker prediction cycle | hourly during market |
| `score.py` | Daily scoring + bandit update | 21:30 UTC |
| `grading.py` | Daily grade-and-reply note + follow-ups | 21:45 UTC |
| `discover.py` | Web-search-driven discovery (F09) | 2x/day |
| `discovery_engine.py` | Forward-looking FWP composite scoring (F19) | 23:00 UTC |
| `features.py` | Per-news structured feature extraction | per ingest tick |
| `intent.py` | Inbox message intent classifier | per inbound |
| `thesis.py` | Atomic-claim extract + verify (F16) | post-prediction |
| `events.py` | Tracked event predictions + verification (F26) | nightly 21:50 |
| `qa_deepdive.py` | Progressive Q&A dive on a ticker (F37) | on-demand + Sat 07:00 |
| `tech_dive.py` | Structured 4-round tech topic deep-dive (F43) | on-demand + daily 04:30 UTC sector-rotated |
| `analyst_skills.py` | F44: earnings_review (3-round) / dd_checklist (1-shot) / morning_note from Anthropic FSI patterns | on-demand |
| `pdf_export.py` | Markdown -> PDF + HTML output (weasyprint -> xhtml2pdf fallback) | on-demand |
| `self_review.py` | Daily review packet + auto-rewrites (F18) | 06:00 UTC |
| `ai_loop_monitor.py` | AI commercial-loop closure monitor (F39) | weekly Mon 06:30 |
| `learn.py` | Weekly reflection + bandit calibration | Sat 06:00 |
| `prompt_rewriter.py` | LLM-driven prompt rewrite proposals | self_review-triggered |

### Data / scanner modules (no LLM)
| Module | Feature | Frequency |
|---|---|---|
| `tech_trends.py` | Trend atlas (F41) + conviction watchlist (F42) loader/mutator/renderer | render-time |
| `smallcap_scanner.py` | F38 3-sector small-cap forward scan | nightly 22:15 |
| `options.py` | F36 unusual-options-activity detector | nightly 21:55 |
| `holdings.py` | YAML-synced portfolio table | render-time |
| `secular.py` | Secular themes (F25) loader / day-rotation | render-time |
| `stops.py` | F24 ATR + swing-low + percent stop-loss | render-time |
| `anomaly.py` | F12 daily price+volume anomaly flagger | 16:00 UTC |
| `alerts.py` | F28+F32 holding sell-trigger keyword scanner | per ingest tick |
| `action_queue.py` | F11 deep-dive follow-up queue | research-driven |
| `cloud_sync.py` | Render-side /sync/* endpoints + local sync runner | 5s cron |
| `backup.py` | Nightly online SQLite backup (F33) | 23:30 UTC |

### Ingest
| Module | Source |
|---|---|
| `ingest/__init__.py` | dispatch wrappers |
| `ingest/news.py` | Yahoo + RSS feeds |
| `ingest/prices.py` | yfinance daily OHLCV (end=tomorrow per fix d5a04dc) |
| `ingest/insiders.py` | EDGAR Form 4 ATOM + XML body parser (F35) |

### Boundaries / IO
| Module | Role |
|---|---|
| `webfetch.py` | URL fetch + page extraction |
| `websearch.py` | Search adapter |
| `wechat.py` / `wechat_gui.py` / `wechat_inbox.py` | (legacy, mostly disabled per 2026-05-04 directive to remove WeChat coupling) |
| `conversation.py` | Recipient-token conversation log + memory |

## data/ -- curated YAML inputs

| File | What | Edit how |
|---|---|---|
| `watchlist.yaml` | 39-ticker ingest universe (US AI capex + China semis) | edit text or `stock watchlist` CLI |
| `holdings.yaml` | Portfolio holdings | edit text; `stock holding add` for new |
| `secular_themes.yaml` | 5 long-horizon narratives (china_aging, china_semi_value, etc.) | edit text |
| `tech_trends.yaml` (**F41**) | 10 specific tech trends w/ evidence + falsification + vehicles | `stock trend list/show/toggle/swap/add/remove` or edit text |
| `conviction_watchlist.yaml` (**F42**) | Deeply-tracked tickers, 1+ per trend | `stock conviction list/toggle/swap/add/remove` or edit text |
| `smallcap_universe.yaml` | 33 small-caps across 3 sectors (F38) | edit text |
| `topic_queue.yaml` | F43 daily-dive topic rotation (9 topics across 3 sectors) | edit text or `stock topic add` |
| `company_dive_queue.yaml` | F44 company DD rotation (~28 companies, priority-tiered) | edit text |
| `ai_supply_chain.yaml` | AI capex layered chain map | edit text |
| `feedback_rules.yaml` | Boss-feedback derived response rules | self-rewriter updates |

## prompts/ -- LLM prompt templates

| File | Used by |
|---|---|
| `research.txt` | research.py daily note (heavily structured w/ ~20 placeholders) |
| `feature.txt` | features.py per-news extraction |
| `intent_classify.txt` | intent.py |
| `thesis_extract.txt` / `thesis_verify.txt` | thesis.py |
| `event_verify.txt` | events.py |
| `discover_extract.txt` | discover.py |
| `self_review.txt` | self_review.py |
| `tech_dive.txt` (**F43**) | tech_dive.py 4-round structured dive |
| `vision_extract.txt` | image upload vision pipeline |
| `rewrite_prompt.txt` | prompt_rewriter.py meta |

## DB tables (managed by db.py executescript)

| Table | What |
|---|---|
| `news` | ingested articles (Yahoo + RSS + SEC) |
| `prices` | yfinance daily OHLCV |
| `features` | extracted news features (per-news LLM output) |
| `predictions` | per-ticker prediction rows |
| `predictions_scored` | scored outcomes |
| `research_reports` | all generated notes (kind=daily/grading/reply/alert/deep_qa/trade_log/tech_dive) |
| `watchlist` | DB shadow of watchlist.yaml |
| `holdings` | DB shadow of holdings.yaml |
| `insider_filings` | F35 SEC Form 4 (ticker, filer, code, shares, price, role) |
| `discovery_candidates` | F19 forward-discovery FWP scores |
| `tracked_events` | F26 predicted catalyst events + outcomes |
| `option_anomalies` | F36 UOA detections |
| `smallcap_candidates` | F38 small-cap scan results |
| `ai_loop_health` | F39 panel measurements |
| `tech_dive_runs` (**F43**, new) | Each tech-dive's metadata: topic, sector, rounds, research_id |
| `price_anomalies` | F12 daily anomaly flags |
| `action_queue` | F11 follow-up topic queue |
| `llm_calls` | every LLM call: caller, model, tokens, cost |
| `recipient_tokens` | APK + dashboard auth tokens |
| `conversations` | inbound/outbound message log |
| `wechat_log` | (legacy) |
| `prompt_rewrites` | self-review proposals |

## CLI surface (Typer)

`stock <command>` -- dispatched via `__main__.py`. Sub-apps marked.

### Daily ops
- `serve` -- run orchestrator + API together (entrypoint for the laptop)
- `summary` -- F34 morning view of everything
- `check <ticker>` -- F30 9-section ad-hoc snapshot
- `research` -- generate daily note now
- `report` -- view recent predictions

### Manage data
- `watchlist add/remove/list` -- ingest universe
- `holding add/remove/list/note` -- portfolio
- **`trend list/show/toggle/swap/add/remove`** (F41)
- **`conviction list/toggle/swap/add/remove`** (F42)
- `event add/list/edit/delete/verify/calibration` (F26)
- `thesis extract/verify/stats/show` (F16)
- `forward-discover run/list/dismiss/promote/backtest-winners` (F19)

### Run scanners on demand
- `smallcap-scan` (F38)
- `uoa-scan` (F36)
- `ai-loop-measure` (F39)
- `weekly-qa-dive` (F40)
- `qa-dive <ticker>` (F37)
- **`tech-dive <topic> [--sector ...]`** (F43)
- **`earnings-review <ticker>`** (F44, equity-research style)
- **`dd-checklist <ticker>`** (F44, 12-item punch list)
- **`morning-note`** (F44, overnight roll-up)
- **`entry-zone <ticker>`** -- pullback entry-zone analysis (MA + swing-low + ATR + percent)
- **`pdf-export research:<id> | file:<path> | recent-dives`** -- weasyprint or xhtml2pdf
- `anomaly-run` (F12)
- `backend show/set/test` (claude_cli vs minimax flip)

### Reports
- **`daily-zh`** (new) -- Chinese activity report for the day

## Cron schedule (26 jobs)

Run order on a typical Mon-Fri:
```
03:15      company_dd_dive (F44 -- 1 company every 4.5h)
04:30 UTC  daily_tech_dive (F43 -- sector rotates by weekday)
07:45      company_dd_dive (F44)
12:15      company_dd_dive (F44)
16:45      company_dd_dive (F44)
21:15      company_dd_dive (F44)
06:00      daily_self_review
06:30      ai_loop_measure (Mon only)
07:00      weekly_qa_dive (Sat only)
14:00-21:45 ingest_and_extract (every 15 min)
14:00-21:00 run_predictions (top of hour)
21:30      score_daily
21:40      thesis_verify
21:45      grade_and_reply
21:50      verify_tracked_events
21:55      uoa_scan
22:15      smallcap_scan
22:30      morning_research_push
23:00      discovery_engine
23:30      backup_db
02:30      morning_research_push (next day)
14:30      evening_research_push
* /5s      sync_to_render (intentional, APK burst-poll)
```

## Backends + cost

- **CORE_LLM_BACKEND**: env var, valid values `claude_cli` (default current) / `minimax`
- All modules call `get_core_client()` -- one flip migrates everything (commit 54c690d)
- claude_cli = subprocess to local Claude Code session, $0 incremental cost
- MiniMax kept as flip-back path; balance-depleted as of 2026-05-06 (stock backend set minimax NOT recommended until balance restored)

## Deferred / known gaps

- **PDF CJK font** -- xhtml2pdf renders Chinese chars as boxes (no CJK font shipped). HTML output is generated alongside every PDF; boss can open `*.html` in Chrome to read Chinese, or use Chrome's "Save as PDF". Permanent fix is installing GTK + weasyprint OR embedding a CJK TTF in xhtml2pdf -- both deferred until requested
- **盛合晶微** (boss-named): private SMIC packaging JV, no public ticker -- tracked qualitatively only
- **APK feature gap**: image attachment works (F18); Q&A-style threading not yet built
- **Render sync log noise**: 5s cron is intentional but floods orchestrator.log -- log-level tuning deferred
