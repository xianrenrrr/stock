# STOCK — AI supply-chain research harness

Python service that ingests news + prices for an AI supply-chain watchlist,
generates twice-daily Chinese-language research notes via MiniMax + Tavily,
and learns from outcomes (memory, rules, bandit, calibration). Designed to
run continuously either on a Windows laptop with WeChat GUI delivery or
fully in the cloud (Render) with API-only output.

Runtime source of truth: `docs/runtime_source_of_truth.md`.
Agent guidance: `docs/agent_guidance.md`. Coding style: `CLAUDE.md`.
Historical roadmap docs live in `pipeline/`; they are not runtime truth.

## What runs where

| Component | Local (Windows) | Cloud (Render) |
|---|---|---|
| News + price ingestion (yfinance, RSS, EDGAR) | ✅ | ✅ |
| MiniMax LLM (features, predictions, research, deep dives) | ✅ | ✅ |
| Tavily web discovery + LLM extraction | ✅ | ✅ |
| Predictions, scoring, bandit, calibration, weekly reflection | ✅ | ✅ |
| Action-queue auto-runner (F11) | ✅ | ✅ |
| Anomaly flagger / holdings tracker / SEC Form 4 (F12) | ✅ | ✅ |
| Conversation memory + intent + auto-rewrite (F13) | ✅ | ✅ |
| FastAPI on `/stock/...` for skill / future APK | ✅ | ✅ |
| **WeChat delivery via pyautogui** | ✅ | ❌ no desktop |
| **OpenClaw subprocess trigger** | ✅ | ❌ |
| **WeChat inbox screenshot pulls** | ✅ | ❌ |

In cloud mode the orchestrator generates notes and persists them to the DB,
exposed via `GET /stock/research/latest` for downstream consumers (custom APK
channel, dashboard, webhook, etc.).

## Cloud deploy on Render (recommended)

```
1. Push this repo to GitHub.
2. Sign in at render.com, click "New > Blueprint".
3. Point Render at the GitHub repo.
4. Render reads render.yaml, prompts for secret env vars.
5. Set the secrets in the dashboard (see "Required env vars" below).
6. Click apply. First deploy takes ~5 minutes.
```

Step-by-step + troubleshooting: `pipeline/plan_G_render_deploy.md`.

### Required env vars (set in Render dashboard)

| Key | Required? | Purpose |
|---|---|---|
| `MINIMAX_API_KEY` | yes | LLM workhorse for features, predictions, research, discovery |
| `ANTHROPIC_API_KEY` | optional | Claude Opus weekly reflection + auto-rewriter; falls back to MiniMax if absent |
| `STOCK_API_TOKEN` | yes (Render auto-generates) | Bearer auth for the FastAPI endpoints |
| `TAVILY_API_KEY` | yes (or SERPER/BRAVE) | Web discovery |
| `DAILY_COST_CEILING_USD` | default 10 | Hard kill switch on LLM spend per UTC day |
| `RESEARCH_LANGUAGE` | default `zh` | `zh` or `en` |
| `MINIMAX_BASE_URL` | default `https://api.minimaxi.com/v1` | Override if your MiniMax key was issued for the global host |
| `DAILY_REPORT_EMAIL_TO` | default `2001liqiyangdaily@gmail.com` | Daily action report and failure-alert recipient |
| `SMTP_FROM` | default `2001liqiyangdaily@gmail.com` | Sender address for daily reports and failure alerts |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | optional | Required for actual email delivery |

Cloud-specific defaults (already set in `render.yaml`):
- `OPENCLAW_AUTO_DELIVER=false`
- `WECHAT_PUSH_URL=""` (empty)
- `DB_PATH=/var/data/stock.db`

## Local install (Windows, full features incl. WeChat GUI delivery)

```powershell
cd C:\Users\claw\Desktop\Project\STOCK
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[gui,dev]
copy .env.example .env
# edit .env to add your keys
.venv\Scripts\python.exe -m stock serve
```

The `[gui]` extra adds `pyautogui`, `pyperclip`, `pyscreeze`, `pillow` — only
needed for the WeChat GUI delivery path on Windows. Skip it (`pip install -e .`)
for headless / cloud installs.

## Test

```bash
python -m pytest tests/ -q
# 242 tests, all green
```

## CLI commands

```
stock ingest news <ticker>     # pull news for a ticker (Yahoo + RSS + EDGAR)
stock ingest prices <ticker>   # pull daily OHLCV
stock predict <ticker>         # one-shot prediction
stock score                    # score every due prediction
stock report --days 7          # hit rate / Brier / spend report
stock reflect [--dry-run]      # weekly rules rewrite
stock discover [--layer X]     # autonomous web discovery cycle
stock research [--push]        # generate a fresh daily research note
stock deep-dive <topic>        # on-demand topic deep dive
stock chain [--layer X]        # inspect the AI supply chain map
stock action-queue list/run    # F11 auto-queued action items
stock holding add/remove/list  # F12 portfolio holdings
stock anomaly run              # F12 volume/price anomaly flagger
stock pull-feedback            # F13 manual feedback screenshot pull (local only)
stock add-feedback <recipient> "<text>"  # F13 manual reply transcription
stock deliver [--now]          # local pyautogui WeChat send
stock serve                    # run everything (FastAPI + scheduler)
```

## Repo layout

```
src/stock/                      # all business logic
prompts/                        # LLM prompt templates
data/                           # config (watchlist.yaml, holdings.yaml, ai_supply_chain.yaml)
                                # + runtime DB and outbox (gitignored)
tests/                          # pytest suite (242 tests)
pipeline/                       # design + roadmap docs (MASTER_PLAN.md, plan_A..plan_G.md)
openclaw_skill/                 # OpenClaw skill manifest for local Windows boss-channel
scripts/                        # install + helper scripts
Dockerfile + render.yaml        # cloud deploy
```

## License

Private project — no public license. Do not redistribute.
