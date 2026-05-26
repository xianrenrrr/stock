# Feature Backlog

Last cleaned: 2026-05-25.

This file is a lightweight feature ledger. It is not the runtime source of
truth. Use `docs/runtime_source_of_truth.md` for active schedules and
`docs/agent_guidance.md` for agent behavior.

## Status Key

- `DONE` - implemented.
- `MANUAL` - implemented but not scheduled.
- `DISABLED` - implemented but intentionally not scheduled.
- `TODO` - not implemented.

## Current Feature Ledger

| ID | Feature | Status | Runtime note |
|---|---|---|---|
| F00-F08 | Core ingest, prediction, scoring, report, memory, bandit, calibration, orchestrator | DONE | Active through scheduler/CLI. |
| F09 | Web discovery | DONE | Runs before both daily research pushes. |
| F11 | Action-items auto-queue | DONE | Runner at 00:00 and 12:00 UTC when queue has pending items. |
| F12 | Holdings, anomalies, health checks | DONE | Anomalies daily; health check weekly Saturday. |
| F13 | Conversation memory and prompt rewrite | DONE | Feedback loop every 5 min. |
| F16 | Thesis extraction/verification | DONE | Verification runs Mon-Fri after scoring. |
| F17 | Core backend switch | DONE | `codex_cli`, `claude_cli`, `minimax`. |
| F18 | Self-review/autopilot | DONE | Daily at 06:00 UTC. |
| F19 | Forward discovery engine | DONE | Mon-Fri 23:00 UTC. |
| F24 | Stops and entry zones | DONE | Used in research; entry scan weekly Sunday. |
| F26 | Tracked events | DONE | Verified Mon-Fri 21:50 UTC. |
| F33 | SQLite backup | DONE | Daily 23:30 UTC. |
| F36 | UOA and options ratio tracking | DONE | Mon-Fri 21:55 UTC. |
| F37 | Q&A deep-dive engine | DONE | Manual plus F40 weekly automation. |
| F38 | Small-cap scanner | DONE | Mon-Fri 22:15 UTC. |
| F39 | AI commercial-loop monitor | DONE | Weekly Monday 06:30 UTC. |
| F40 | Weekly Q&A deep dive | DONE | Saturday 07:00 UTC. |
| F41 | Tech trend radar | DONE | Used in daily research prompt. |
| F42 | Conviction watchlist | DONE | Used in daily research and entry scan. |
| F43 | 4-round tech-dive engine | DONE | Weekly Sunday 04:30 UTC plus manual `stock tech-dive`. |
| F44 | Analyst skills/company DD | DONE | Company DD weekly Wednesday; earnings/morning note manual. |
| F45 | Entry-signal scan | DONE | Weekly Sunday 06:00 UTC. |
| F46 | Post-close volume snapshot | DONE | Mon-Fri 20:05 UTC. |
| F47 | Daily actions report | TODO | Proposed: one file/report that says what the operator should do today. |

## Adding New Features

When adding a feature:

1. Add a row here with `TODO`.
2. Implement in `src/stock/`.
3. Add tests.
4. If it changes runtime behavior, update `docs/runtime_source_of_truth.md`.
5. If it changes agent behavior, update `docs/agent_guidance.md` or `CLAUDE.md`.
