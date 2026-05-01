# Quick commands — check if boss's messages reached Render

Open PowerShell on the laptop and paste any of these.

## 1. List all inbound replies on Render since yesterday

```powershell
curl.exe -H "Authorization: Bearer sEfSjNeY9KkQ7TnL4EGlowUhmA4UVjW8NFdFPDbir/A=" "https://stock-research-9aq3.onrender.com/sync/replies?since=2026-04-30T00:00:00%2B00:00"
```

If `"replies":[]` → boss's messages never reached Render.
If you see body text → they reached Render. Issue is on the laptop pull side.

## 2. Health check (sanity test that Render is alive)

```powershell
curl.exe https://stock-research-9aq3.onrender.com/stock/health
```

Should return `{"status":"ok","port":18790}`.

## 3. Identity check with the boss's token (proves auth works)

```powershell
curl.exe -H "Authorization: Bearer ODIyu2N8baAS6qa2qJl7JriA0iUPwd8U" "https://stock-research-9aq3.onrender.com/channel/api/me"
```

Should return `{"recipient":"杨建中", ...}`.

## 4. List the latest 14 days of research notes (what the APK sees)

```powershell
curl.exe -H "Authorization: Bearer ODIyu2N8baAS6qa2qJl7JriA0iUPwd8U" "https://stock-research-9aq3.onrender.com/channel/api/notes?days=14"
```

## 5. Check local laptop conversations table (what F13 has actually processed)

```powershell
.venv\Scripts\python.exe -c "import sqlite3; c = sqlite3.connect('data/stock.db'); rows = c.execute('SELECT id, recipient, direction, intent, body, created_at FROM conversations ORDER BY created_at DESC LIMIT 10').fetchall(); [print(r) for r in rows]"
```

Shows the 10 most recent conversation turns. Look for `direction='inbound'` rows from the boss.

## 6. Check whether the laptop pulled anything in the last hour

```powershell
Select-String -Path pipeline/logs/orchestrator.log -Pattern "replies=[1-9]|Inline F13"
```

If empty → no boss replies were pulled.
If you see lines → they were pulled and processed.
