# Plan G — Render deployment + GitHub workflow

Goal: ship the entire STOCK system to Render so it runs 24/7 in the cloud,
with the codebase mirrored on GitHub. Local Windows laptop becomes optional
(only needed if you still want pyautogui WeChat delivery).

This plan replaces nothing — it's a deployment recipe, executed once.

## What changed in the codebase to enable this

1. `pyautogui` + `pyperclip` moved to `[gui]` optional extra in `pyproject.toml`
   so they don't break Linux installs.
2. `wechat_gui.py` and `wechat_inbox.py` got `try/except` import guards;
   GUI delivery + inbox screenshot are no-ops on cloud (clear log warning).
3. New `Dockerfile` (multi-stage, Python 3.12-slim base).
4. New `render.yaml` (Render Blueprint with one web service + 1 GB disk).
5. New `.dockerignore` and tighter `.gitignore`.
6. `DB_PATH` env now respected (Render mounts persistent disk at `/var/data`).

## What you need to give me

Nothing new — already have:
- `MINIMAX_API_KEY` ✓
- `TAVILY_API_KEY` ✓
- `STOCK_API_TOKEN` (Render auto-generates a fresh one anyway)

What you need from yourself:
1. **GitHub account** + a fresh empty private repo (or use an existing one).
2. **Render account** (free signup at render.com, no credit card needed for
   the free tier; starter tier is $7/mo for always-on).

Optional (for richer features):
- `ANTHROPIC_API_KEY` — used by the F13 prompt-rewriter when daily budget allows.
- `SERPER_API_KEY` or `BRAVE_API_KEY` — fallback search backends.

## Step-by-step

### 1. Local sanity check (5 min)

```powershell
cd C:\Users\claw\Desktop\Project\STOCK
.venv\Scripts\python.exe -m pytest tests/ -q
# expect: 242 passed
```

If anything fails here, stop — fix locally before pushing to GitHub.

### 2. Initialize git and push to GitHub (10 min)

```powershell
cd C:\Users\claw\Desktop\Project\STOCK
git init
git add .
git status
# scan output: confirm .env is NOT listed, data/stock.db is NOT listed,
# data/wechat_outbox/* is NOT listed (the .gitignore should hide them).

git commit -m "Initial commit: F00-F13 stock research system"

# Create a private repo on github.com first, then:
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

### 3. Render setup (10 min)

1. Sign in at https://dashboard.render.com → click **New +** → **Blueprint**.
2. Connect your GitHub account, pick the repo you just pushed.
3. Render reads `render.yaml` and shows a preview of the service it will
   create: one web service named `stock-research`, runtime Docker, with a
   1 GB persistent disk.
4. Click **Apply Blueprint**.
5. Render prompts you for the secret env vars marked `sync: false`:
   - `MINIMAX_API_KEY` → paste your MiniMax key
   - `ANTHROPIC_API_KEY` → paste or leave blank
   - `TAVILY_API_KEY` → paste your Tavily key
   - `SERPER_API_KEY` / `BRAVE_API_KEY` → leave blank
   - `STOCK_API_TOKEN` → Render auto-generates a strong value, copy it
     somewhere safe (you'll need it to call the API)
6. Click **Save**, then **Deploy**.

First build takes ~5-7 minutes (Docker layer cache is empty).
Watch the build logs in the dashboard.

### 4. Verify deployment (5 min)

After "Deploy live":

```bash
# Render gives you a URL like https://stock-research-xxxx.onrender.com

# Health check (no auth required):
curl https://stock-research-xxxx.onrender.com/stock/health
# expect: {"status":"ok","port":<some-port>}

# Authenticated check:
curl -H "Authorization: Bearer <YOUR_STOCK_API_TOKEN>" \
     https://stock-research-xxxx.onrender.com/stock/chain
# expect: JSON with the 5 supply-chain layer names
```

### 5. Trigger the first research note (3 min)

```bash
# Discovery cycle (will pull from Tavily + extract via MiniMax)
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{}' \
     https://stock-research-xxxx.onrender.com/stock/discover

# Daily research generation
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{}' \
     https://stock-research-xxxx.onrender.com/stock/research

# Read the latest note
curl -H "Authorization: Bearer $TOKEN" \
     https://stock-research-xxxx.onrender.com/stock/research/latest
```

After that, the scheduler keeps generating one twice a day (10:30 / 22:30
Beijing). The stored notes are queryable via the API forever (subject to
disk size).

## Operational notes

### Cost

| Plan | Monthly | Behavior |
|---|---|---|
| `free` web service | $0 | Sleeps after 15 min idle. **Scheduler stops sleeping** — morning/evening pushes will be missed |
| `starter` web service | $7 | Always-on. Recommended. |
| 1 GB persistent disk | $0.25 | Holds SQLite DB |

So **$7.25/mo for the always-on path**. The MiniMax + Tavily costs are on
top, capped by `DAILY_COST_CEILING_USD` (currently $10/day).

### Updating the deployment

Push to `main`, Render auto-redeploys (`autoDeploy: true` in `render.yaml`).
Build cache speeds repeated builds to ~1-2 min unless `pyproject.toml`
changes.

### Viewing logs

Render dashboard → Logs tab. The Python `logging` output streams live.
Useful to confirm scheduled jobs are firing:

```
Scheduled: Morning research + WeChat push -> 2026-04-29T02:30:00+00:00
INFO  Discovery id=N layer=...
INFO  Research generated id=N cost=$0.012
INFO  pyautogui not available -- skipping GUI delivery for 2 task(s)
```

That last line is **expected** in cloud mode — pushes still persist to the
DB; they just don't try to drive a (nonexistent) WeChat desktop.

### How does the boss read the notes in cloud-only mode?

Three options:

1. **Plain HTTP** — open `https://stock-research-xxxx.onrender.com/stock/research/latest`
   in his browser with the bearer token in a header (use a browser extension
   like ModHeader). Simplest, no app to install.
2. **Custom APK channel** (Plan F) — build a small WebView APK that points at
   the Render URL with the token baked in. He installs once, opens to read.
   ~8 hours to build. China reachability of `*.onrender.com` needs testing
   first; if blocked, fall back to Aliyun-CN frontend (Plan F's option B).
3. **Telegram bot** — out of scope per user direction.

### Disk lifecycle / DB migrations

Render persistent disks survive service restarts and redeploys. The schema
uses `CREATE TABLE IF NOT EXISTS` everywhere so adding columns later means
adding a migration step (we don't have one yet — F11/F12/F13 add tables, not
columns to existing ones, so additive is fine for now).

If you ever need to nuke the DB and start fresh:
- Render dashboard → Disks → `stock-data` → click **Empty disk**.

### Backups

Currently none. The DB has all your prediction history + research notes.
For 1 GB of data the simplest backup is a daily `sqlite3 .backup` to S3 or
similar; not built today. **Risk: if Render loses the disk, you lose all
generated history.** Plan H if you want this.

## Risks / mitigations

| Risk | Mitigation |
|---|---|
| Render free tier sleeps → missed pushes | Starter plan ($7/mo) |
| `*.onrender.com` blocked from China | Test from boss's network; fall back to Aliyun-CN proxy in Plan F |
| First sentence-transformers cold load on free tier slow | Starter tier keeps the worker warm; or pre-cache during Docker build |
| Pip install of `sentence-transformers` is heavy (~500 MB) | Add a pre-build cache layer in Dockerfile (current Dockerfile copies src first to cache deps) |
| Disk fills up | Monitor `/var/data` usage; rotate old `research_reports` rows after N days |
| Secrets in git | `.gitignore` excludes `.env`; render uses dashboard-stored secrets |

## What does NOT come with this deploy

- No WeChat delivery (deliberate — cloud has no desktop)
- No OpenClaw integration (same reason)
- No automatic boss-replies (until Plan F APK ships)
- No frontend dashboard (the API is JSON-only; build a one-page HTML if needed)

These are addressable in follow-up plans (F for APK, H for backups, etc.).

## Total time

| Phase | Time |
|---|---|
| Local sanity check | 5 min |
| GitHub init + push | 10 min |
| Render setup + first deploy | 15 min |
| Verify | 5 min |
| **Total** | **~35 min** |
