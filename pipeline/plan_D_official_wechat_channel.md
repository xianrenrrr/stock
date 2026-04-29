# Plan D — Official WeChat Channel (Tencent plugin) — research notes

## TL;DR — privacy reality first

**Tencent sees every message regardless of which channel option you choose.**
WeChat is not end-to-end encrypted. Personal app, official plugin, third-party
protocol, or WeCom webhook — all routed through Tencent servers with full
content access for compliance, anti-fraud, and government cooperation.

This plan is about *which technical path is least likely to get the account
banned*, not about content privacy. For content-private comms: switch
platform (Telegram bot is the cleanest swap; ~30 lines of code to retarget).

## Three viable channel paths

| Path | Compliance | Receive boss reply | Send | Setup difficulty | Stability |
|---|---|---|---|---|---|
| ① 3rd-party protocol (Wechaty PadLocal, valkyofc plugin) | Violates ToS — ban risk | Push events | Yes | Medium (QR scan) | Low |
| ② Tencent official `@tencent-weixin/openclaw-weixin` | Compliant | Push events | Yes | Low | High |
| ③ WeCom webhook bot | Compliant | Webhook one-way only | HTTP POST | Trivial | Very high |

## Recommendation: Path ② — `@tencent-weixin/openclaw-weixin`

Why:
- Tencent-maintained plugin, no ban risk
- Integrates with existing OpenClaw gateway you already run
- Supports private chats + media (group chats not yet — irrelevant for current yjz/richard recipients)
- Plugin checks OpenClaw host version and refuses to load if incompatible

Why not ①: `valkyofc/openclaw-wechat-channel`, Wechaty PadLocal, etc. all
inject through unofficial Pad/iPad/Mac protocols. Personal account ban risk
is real (Tencent 2026 rules explicitly target automation tools).

Why not ③: Single-direction (can send, can't receive replies). Defeats the
purpose of the feedback loop in F13.

## Requirements

- **Node.js**: 22.14+ (24 recommended). Already met (current OpenClaw 2026.4.12 runs on user's box).
- **OpenClaw**: installed via npm globally (already done).
- **WeChat Desktop**: must be logged in on the same Windows machine (already done).
- Internet access to Tencent endpoints (probably check that `api.weixin.qq.com` resolves from this machine — same DNS-from-US issue we hit with `api.minimaxi.com` may apply).

## Installation steps (target)

```powershell
# 1. Install the plugin via OpenClaw's plugin manager
openclaw plugins install @tencent-weixin/openclaw-weixin

# 2. Verify the plugin loaded
openclaw plugins list | Select-String wechat

# 3. Configure the channel (interactive)
openclaw configure --section channels
# choose wechat -> follow prompts; will prompt for QR scan on first run

# 4. Verify channel state
openclaw channels list
# expect: wechat ready

# 5. Restart the gateway so the new plugin is wired
& "$env:USERPROFILE\.openclaw\gateway.cmd"

# 6. Smoke test: send a self-message via OpenClaw
openclaw message send --channel wechat --to <self-alias> --message "channel test"
```

## STOCK system integration plan

Replace `wechat_gui.deliver_pending()` calls with channel-API calls.

| Current (pyautogui) | After Path ② |
|---|---|
| Click WeChat icon, paste, Enter | `openclaw message send --channel wechat --to <alias>` |
| Take post-send screenshot for proof | Tencent message_id is the proof |
| 5-min screenshot polling for replies | `openclaw channels listen` event stream → webhook |
| Operator transcribes screenshots into `wechat_feedback.md` | Auto-write inbound events to `wechat_feedback.md` and `conversations` table |

### File changes table (target)

| File | Change | What |
|---|---|---|
| `src/stock/wechat_channel.py` | new | Calls OpenClaw `channels.send` over loopback HTTP/WS; subscribes to inbound events |
| `src/stock/wechat.py` | edit | `broadcast()` gains `mode=channel` branch; `mode=gui` retained as fallback |
| `src/stock/orchestrator.py` | edit | New `_job_listen_inbound()` (or hook subscription) writes inbound events |
| `.env.example` | edit | `WECHAT_CHANNEL_MODE = "channel" or "gui"` (default channel once ② installed) |
| `openclaw_skill/stock.skill.md` | edit | Document channel mode + fallback |

### Fallback policy

- If `channels.send` returns error → fall back to `wechat_gui.deliver_pending()`
- If `wechat ready` is not present in `channels list` at orchestrator startup → log warning, set effective mode to `gui`
- Never both at once — channel and GUI both pressing Enter would dupe messages

## Open questions to resolve before implementation

1. **DNS reachability of Tencent endpoints from US laptop** — same risk as `api.minimaxi.com`. Run `nslookup api.weixin.qq.com` ahead of time. If flaky, add same retry/backoff as in `models.py`.
2. **Plugin version pinning** — `@tencent-weixin/openclaw-weixin` checks OpenClaw host version. Pin both in CI / setup notes so a plugin update can't silently break us.
3. **QR scan refresh cadence** — sessions expire periodically; need a re-scan reminder via the orchestrator (probably a daily check that emits a notification when the channel goes "needs reauth").
4. **Group chat support timing** — currently private-chat only per plugin metadata. If boss ever wants group push, we'd fall back to GUI for those targets.

## Time estimate

- Setup (interactive config + smoke test): ~30 min — much depends on how clean the QR-scan flow is.
- Code integration (`wechat_channel.py` + `broadcast` branch + tests): ~2-3 hours.
- Migration + parallel-run period (channel + GUI both writing outbox, compare): ~1 day of observation.

## Risks

- **Plugin breakage on OpenClaw upgrade**: pinned versions; doctor surfaces incompatibility.
- **QR session expiry**: hard fail mode; revert to GUI delivery when channel reports unauthorized.
- **Tencent endpoint DNS issues from US ISP**: same retry pattern we already have in `models.py`.
- **Tencent ToS shifts**: even the official plugin is subject to Tencent policy changes; track release notes.

## Comparison cheat sheet for future-me

If you only have 30 minutes: install ②, smoke-test, then call it a night. The
GUI fallback already works; the channel path just gets you push-event replies
and removes the polling-by-screenshot ugliness.

If you'd rather not touch this layer at all: keep the existing pyautogui
delivery + `pull-feedback` screenshot routine. It works; it's just labor-intensive.

If you want true content privacy: switch to Telegram bot (`python-telegram-bot`
library). One env var (`TELEGRAM_BOT_TOKEN`), one chat-id per recipient.
~30 lines, no QR scan, no ban risk, content not visible to Tencent.
