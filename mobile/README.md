# Mobile — AI 研报 Android app

Native Kotlin / Jetpack Compose app that talks directly to the Render-hosted
`/channel/api/*` endpoints. No WebView, no URL visible to the user — just a
real Android app: home-screen icon, opens to today's research note, reply box,
14 days of history.

## Architecture

```
Compose UI  →  StockViewModel  →  StockClient (HttpURLConnection + JSON)
                                       │
                                       └→  https://stock-research-9aq3.onrender.com/channel/api/*
                                            (Bearer token baked into BuildConfig at compile time)
```

Endpoints called:
- `GET /channel/api/me`            — identity check on first open
- `GET /channel/api/notes?days=14` — list recent notes
- `GET /channel/api/notes/{id}`    — full body of a specific note
- `POST /channel/api/reply`        — submit boss reply

The boss's token is baked into `BuildConfig.API_TOKEN` via `STOCK_DEFAULT_TOKEN`
at build time. Each recipient gets a separate APK build with their own token.

```
mobile/
  app/
    src/main/
      java/com/stock/research/MainActivity.kt   ← single-activity WebView
      res/                                       ← icons + theme + strings
      AndroidManifest.xml
    build.gradle.kts
    proguard-rules.pro
  build.gradle.kts                               ← top-level
  settings.gradle.kts
  gradle.properties                              ← STOCK_BASE_URL goes here
```

## How it works

The app launches `BuildConfig.WEBVIEW_URL` (set at build time from
`gradle.properties`). The dashboard handles auth — the WebView's localStorage
remembers the token so subsequent opens skip the login screen.

If you set `STOCK_DEFAULT_TOKEN` at build time, the URL becomes
`https://.../channel/?token=<TOKEN>` and the dashboard auto-stores it on
first open. Useful for handing each recipient a pre-authenticated APK.

## Build options

You don't need Android Studio or any local Android SDK. The repo ships a
GitHub Actions workflow at `.github/workflows/build-apk.yml` that builds a
signed-debug APK on every push touching `mobile/**`.

### Option A — GitHub Actions (recommended)

1. Update `STOCK_BASE_URL` in `mobile/gradle.properties` to point at your
   live Render URL, e.g. `https://stock-research-xxxx.onrender.com/channel/`.
2. (Optional) set `STOCK_DEFAULT_TOKEN` to bake a recipient token in.
   Each recipient gets a separate APK build by editing this value.
3. `git commit -am "mobile: pin URL" && git push`
4. GitHub → Actions tab → wait for "Build Android APK" to finish (~3-5 min)
5. Download the APK artifact from the run page → send to your boss
   (any chat, the firewall already passed the empty-APK test)

### Option B — local build (Linux/macOS/Windows with JDK 17 + gradle 8.5)

```bash
cd mobile
gradle assembleDebug
# output: app/build/outputs/apk/debug/app-debug.apk
```

### Option C — per-recipient pre-tokenized APK

For recipients who shouldn't see a login screen at all:

1. Mint a token: `python -m stock channel-token issue 杨建中`
2. Edit `mobile/gradle.properties`: paste the token into `STOCK_DEFAULT_TOKEN`.
3. Optionally edit `app_name` in `res/values/strings.xml` to e.g. `研报-杨`.
4. Push → GitHub Actions builds a recipient-specific APK.
5. Reset `STOCK_DEFAULT_TOKEN=` and rebuild for the next recipient (or
   maintain a separate branch per recipient).

## Install on the boss's phone

1. Send the APK via WeChat / email / cloud drive.
2. Boss opens it from his file manager.
3. First time, Android prompts to enable "未知来源 / Install from Unknown
   Sources" for the file manager app. Tap allow.
4. Install → home-screen icon appears.
5. Open → if URL has a token, dashboard loads the latest research note
   immediately. Otherwise login screen.

## What's deliberately NOT in this build

This is a **private installable APK**, not a Play Store app. Don't worry about:

- **No push notifications.** The dashboard polls every 5 minutes while the
  app is open. The boss opens the app when he wants to read; no
  notifications wake him up. **No Firebase, no extra API keys, no
  server-side push setup.**
- **No Play Store.** Debug-signed APK installs directly via "未知来源 /
  Unknown sources". Once the boss enables that toggle the first time, all
  subsequent installs / updates are one tap.
- **No offline mode.** Render must be reachable for the dashboard to load.
  If you ever lose internet, just retry.
- **Dark theme only.** Matches the dashboard's CSS.

These are deliberate trade-offs that keep the build simple and free of
external dependencies. The app does exactly one thing: show your boss the
latest research note, and let him reply. That's it.
