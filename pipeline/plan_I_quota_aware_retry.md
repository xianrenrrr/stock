# Plan I — CLI session quota monitoring + 5-hour leftover-job retry

Status: BOSS DIRECTIVE recorded 2026-06-09. Not implemented. Builds on the
job_runs ledger and `stock usage` shipped 2026-06-09 (commit b1b3a11).

## The directive (boss, 2026-06-09)

Codex CLI and Claude CLI are subscription backends whose usage limits work on
a **~5-hour rolling session window — the quota refreshes every 5 hours**. So:

1. **Monitor the model usage per CLI session window**, not just per day —
   we should always know how much of the current 5h window each backend has
   consumed and whether we are nearing/over the limit.
2. **A job that fails on a usage limit is not dead, only deferred.** Leftover
   jobs must be queued and **re-triggered automatically every ~5 hours** when
   the quota window refreshes, instead of silently losing that cycle's work
   (today a usage-limited weekly tech dive would just be gone until next week).

## What exists today

- `llm_calls` logs every call (provider, tokens, caller, created_at).
- `models.py` F17c already DETECTS codex credit/usage-limit errors by regex
  and falls back to claude_cli — but the detection is not persisted, and when
  both backends are exhausted the job just fails.
- `job_runs` (new) records job failures with error text.
- `stock trigger <job_id>` (new) can re-run any scheduled job by id.

## Design sketch

1. **Persist usage-limit events**: when F17c trips, write a
   `usage_limit_events(provider, caller, detected_at)` row (or a classified
   error kind on the llm_calls/job_runs row). This timestamps the start of the
   exhausted window → refresh expected at `detected_at + 5h`.
2. **Window view**: `stock usage --windows` buckets llm_calls into 5h windows
   per provider (calls + tokens per window, current window highlighted, last
   limit event + expected refresh time). Optionally surface "current window
   consumption" in the warning dashboard when a limit event is recent.
3. **Leftover queue + retry job**: a job_runs error whose text matches the
   usage-limit classification marks that job_id as a leftover. A new scheduler
   job `retry_quota_leftovers` (every 30 min, cheap) re-triggers a leftover
   job ONLY when `now >= detected_at + 5h` (quota refreshed), via the same
   function registry `stock trigger` uses. Cap: 2 retries per job per day;
   skip jobs whose next scheduled fire is sooner than the refresh anyway
   (e.g. the 5-min feedback job never needs retry).
4. Record retries in job_runs with trigger='quota_retry' so `stock jobs`
   shows them distinctly.

## Open questions

1. Exact window semantics per provider (rolling vs fixed 5h block; Codex and
   Claude may differ) — calibrate the refresh estimate from observed
   limit-event spacing rather than hardcoding if unclear.
2. Which jobs are worth retrying (research/dives/grading yes; sync/alert
   plumbing no) — probably an allowlist next to the scheduler definitions.

Not financial advice.
