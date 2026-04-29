# Plan F — Custom APK Channel (replaces WeChat for boss comms)

## Goal

Build a private, end-to-end channel between the user's STOCK system on the
24/7 Windows laptop and the boss's Android phone. No Tencent, no Telegram,
no Google as middleman. Boss installs one custom APK, opens it, sees the
research note, can reply. All traffic between his phone and the user's
laptop, full content private from any messaging platform.

## High-level architecture

```
   STOCK (Python/FastAPI)              boss's Android phone
   localhost:18790                  +----------------------+
        |                           | Custom APK           |
        |  /channel/inbox  POST     |  - WebView shell     |
        |  /channel/outbox GET      |    -> tunnel URL     |
        |  /channel/notify ws       |  - or native fetch   |
        |                           |  - shows research    |
        |                           |  - reply form        |
        v                           +----------------------+
   Cloudflare Tunnel /                       ^
   ngrok / FRP / VPS proxy ------------------+
   (tunnel HTTPS to public URL)
```

The APK is just a thin client. All real logic stays in Python on the laptop.

## Three viable architectures

| Path | APK complexity | Backend changes | China-compat | Install friction | Time |
|---|---|---|---|---|---|
| **F.1 WebView wrapping a tunneled URL** | Trivial (~50 lines Kotlin) | New FastAPI routes + auth | Cloudflare Tunnel often blocked from CN; FRP via Aliyun box works | "未知来源" toggle once | 4-6h |
| **F.2 PWA wrapped as TWA via Bubblewrap** | None (Google tooling) | Same as F.1 | Same caveat | Same | 5-8h |
| **F.3 Native Kotlin app with REST polling + push** | Real (~500 lines) | Same | Same | Cleanest UX | 12-20h |

**Recommendation: F.1 (WebView shell)** — simplest, cheapest, works reliably,
and we own every layer.

## Stack for F.1

**Backend (extends existing STOCK FastAPI):**
- New endpoints under `/channel/`:
  - `GET /channel/inbox` — returns the latest N research notes for an authenticated boss session
  - `POST /channel/reply` — body `{text}` → writes to `wechat_feedback.md` + `conversations` table (F13 schema reuses)
  - `GET /channel/notify` — long-poll or SSE for new pushes
  - `POST /channel/auth` — one-time enrollment (boss enters a code the user sets)
- Reuse `STOCK_API_TOKEN` for the device-token model: each boss gets a per-device JWT minted on enrollment.

**Tunnel (network bridge from boss's phone to user's laptop):**
- **Option A (free, simplest):** Cloudflare Tunnel via `cloudflared` — gives a stable HTTPS URL. **Caveat: domain `*.trycloudflare.com` is intermittently blocked from mainland China.** Test from boss's phone before committing.
- **Option B (~$5/mo, reliable from China):** rent a tiny Aliyun ECS in CN region, run FRP (Fast Reverse Proxy). Tunnel laptop:18790 → public CN IP. Boss reaches CN-hosted endpoint with no GFW issues.
- **Option C (free, also reliable):** Tailscale Funnel — works from anywhere except mainland China sometimes.

**Frontend (the HTML the WebView loads):**
- Single-page chat UI: latest research note up top, scrollable, reply box at bottom.
- Server-Sent Events for real-time push when a new note arrives.
- Localized to Chinese (boss-facing).

**APK build:**
- **Option 1 (no Android Studio needed):** Bubblewrap CLI (Google) — turns a PWA into a signed APK in one command:
  ```
  npm i -g @bubblewrap/cli
  bubblewrap init --manifest=https://stock-channel.example/manifest.json
  bubblewrap build
  ```
- **Option 2 (full control):** minimal Kotlin project with `WebView` activity, signed with Android SDK tooling.

**Signing:**
- Generate a keystore once: `keytool -genkey -keystore stock-channel.keystore`.
- Sign with `apksigner` (comes with Android SDK build-tools).
- Pin SHA-256 of the APK so user can verify before sending to boss.

## Component breakdown

| Component | Effort | Notes |
|---|---|---|
| FastAPI `/channel/` routes (inbox, reply, notify, auth) | 1.5h | Extends existing `api.py` |
| `data/channel_devices.yaml` + per-device JWT | 1h | Mint on enrollment |
| Single-page HTML/JS chat UI | 1.5h | Tailwind for speed; ~300 lines |
| Cloudflare Tunnel setup + testing from boss's phone | 1h | If CN-blocked, switch to FRP+Aliyun (+2h, +$5/mo) |
| WebView APK shell (Bubblewrap or Kotlin) | 1.5h | One screen, points at tunnel URL |
| APK signing + sideload instructions for boss | 0.5h | "未知来源" + verify SHA-256 |
| Migrate existing pyautogui delivery → channel POST | 1h | Add `mode=channel` branch in `wechat.py` |
| **Total** | **~8h** | One full session |

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Cloudflare Tunnel blocked from China | Switch to Aliyun FRP — costs ~$5/mo, ~2h extra setup |
| Boss's phone refuses unsigned/untrusted APK | Self-sign + walk through "未知来源" toggle; provide install screenshot guide |
| APK can't reach laptop when laptop is asleep | Laptop is 24/7 dedicated already — fine |
| Boss gets push notification UX worse than WeChat | Use SSE for foreground; android push notifications via Firebase = +complexity. Acceptable tradeoff for v1. |
| Boss replaces phone / reinstalls | Re-enroll via one-time code; ~30s flow |
| Chinese GFW blocks the tunneled URL | If CN-region VPS used (FRP), fully inside CN — no GFW transit |
| APK file blocked by his corporate network | Already tested: empty test APK downloaded fine — firewall does NOT block APK downloads |

## Privacy guarantees vs WeChat

| Layer | WeChat | Custom APK channel |
|---|---|---|
| Message in transit | Tencent servers | TLS direct (laptop ↔ phone via tunnel) |
| Tencent visibility | Full content | None |
| Other 3rd-party visibility | Tencent + Chinese government on demand | Cloudflare/Aliyun TLS metadata only |
| Account ban risk | Real (ToS violation today) | None (it's our app) |
| Compliance scanning | Yes | None |

## Phased build plan

**Phase 1 — backend skeleton (2h)**
Add `/channel/` routes, JWT auth, in-memory message queue. Test from
local browser at `http://127.0.0.1:18790/channel/inbox`.

**Phase 2 — HTML chat UI (1.5h)**
Single page, plain HTML + fetch + EventSource. Localize to Chinese.
Test in browser end-to-end: push a research note from STOCK → see it in
browser → type reply → reply lands in `wechat_feedback.md`.

**Phase 3 — tunnel (1h or 3h)**
- Try Cloudflare Tunnel first. If boss's phone can load the URL → done.
- Otherwise: provision a small Aliyun ECS, install FRP, point laptop:18790
  → CN public IP. Test again from boss's phone.

**Phase 4 — APK build (1.5h)**
Bubblewrap a PWA pointing at the tunneled URL. Sign with self-generated
keystore. Verify SHA-256.

**Phase 5 — boss install (0.5h)**
Send signed APK via the same firewall-tested path (already proven open).
Walk boss through "未知来源 → 安装". Confirm boss can read latest note +
type reply.

**Phase 6 — system migration (1h)**
Add `WECHAT_CHANNEL_MODE=channel` env. `wechat.broadcast()` gains a
`mode=channel` branch that POSTs to the new `/channel/inbox` endpoint
instead of writing to outbox + pyautogui. Keep pyautogui as fallback.
Existing F11/F12/F13 work transparently — they don't care which channel
delivers.

## Open questions before Phase 1

1. **Boss's phone OS version** — Android 7+ for modern WebView. Confirm.
2. **Tunnel from CN** — does boss's phone resolve `*.trycloudflare.com`? Test
   with a quick Cloudflare Tunnel demo before committing time to building.
3. **Notification UX** — is foreground SSE good enough for v1, or do we need
   real Android push (Firebase / UnifiedPush) so boss gets a notification
   when phone is locked? Push complicates the build by ~5h.
4. **One boss vs multiple recipients** — current setup has 杨建中 + richard.
   Does richard also get the new APK, or is he WeChat-only (mixed channels)?

## What NOT to build

- Don't build native Kotlin from scratch in Phase 1 — WebView shell is faster.
- Don't run a chat server (WebSocket session state, presence, typing
  indicators). Inbox+reply is enough.
- Don't roll our own crypto — TLS via tunnel is sufficient. E2E above TLS
  adds little for a 2-party use case where we own both ends.
- Don't try to replace richard's WeChat path until 杨建中 is comfortable on
  the new APK for at least a week.

## When to start

After tonight's F11/F12/F13 subagent finishes. F11+F12+F13 ship via the
existing pyautogui + outbox path; Plan F is a *channel migration* once those
features are stable.
