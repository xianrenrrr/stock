# STOCK — F11/F12/F13 Master Plan

Three-feature roadmap that turns the daily research pipeline from a one-shot LLM
push into a self-improving research loop with real market signals and two-way
conversation memory. F00–F10 are shipped (research generation, web discovery,
WeChat outbox, pyautogui delivery, screenshot-based feedback, auto-trigger).

## Feature summary

| ID  | Name                          | Core value                                                |
|-----|-------------------------------|-----------------------------------------------------------|
| F11 | Action-items auto-queue       | LLM follow-ups become DB-queued deep-dives, not homework  |
| F12 | Anomaly + holdings + insiders | Real market signals (volume, holdings, Form 4) in prompts |
| F13 | Hermes conversation memory    | Two-way RAG-aware WeChat replies + auto prompt rewrites   |

## Build order (recommended)

1. **F12 anomaly flagger sub-feature first** (cheapest, additive, no schema risk).
   It exercises the price-deltas pattern that F11 deep-dives will lean on.
2. **F11 action-items auto-queue.** Builds the `action_queue` table + parser
   that F13's instruction handler will reuse.
3. **F12 holdings tracker + insider fetcher + weekly health-check deep-dive.**
   Re-uses F11's queue runner to fan out per-holding deep-dives.
4. **F13 conversation memory + auto-rewrite.** Lands last because it depends on
   F11 (queue), F12 (holdings as a per-recipient context anchor), and the
   prompt rewriter touches `prompts/research.txt` which both prior features
   already extend.

## Dependencies between features

- F13 step 4 (instruction-driven prompt rewrite) **requires F11** so that an
  inbound "do a deep-dive on TER" gets queued through the same `action_queue`
  rather than a parallel mechanism.
- F13 step 5 (conversation context block) is a prompt extension; it composes
  with F11's "AI 自动跟进" block and F12's "异常波动 / 组合健康度" block —
  the three blocks must coexist under `{max_chars}`. The plan reserves a
  shared budget table.
- F12 weekly health-check shares the deep-dive renderer with F11, so F11's
  queue runner must accept an `extra_context` payload (volume anomaly summary,
  Form 4 transactions). Already present in `generate_deep_dive(extra_context=...)`.

## Total time estimate

| Feature | Sessions | Notes                                                    |
|---------|----------|----------------------------------------------------------|
| F11     | 2        | One for parser+queue, one for prompt + scheduler wiring  |
| F12     | 3        | One per sub-feature: anomaly, holdings, health+insiders  |
| F13     | 3        | Schema+conversation.py, vec index, learn-from-feedback   |
| Total   | **8**    | Aligned with F-series cadence; matches design.md §14     |

## What changes for the user (boss flow)

**Before:** Boss receives a daily WeChat note with "行动清单" listing chores
the analyst should do. Boss replies in WeChat. Operator transcribes the reply
manually with `stock add-feedback`. Next note is generated; the LLM may or may
not adapt.

**After:**
- Boss's "行动清单" disappears as homework — the system queues those follow-ups
  itself and surfaces results as "前一轮跟进" in the next note (F11).
- Note now leads with "异常波动" (volume/price spikes) and "组合健康度"
  (per-holding Form-4 + news + price digest) — concrete market signal, not
  just narrative (F12).
- Boss's WeChat replies are auto-classified as question / instruction / ack.
  Questions get an AI-drafted reply pushed back via the same pyautogui path.
  Instructions like "shorter notes" or "more A-shares" trigger an
  Opus-driven rewrite of `prompts/research.txt` and `data/rules/current.md`,
  applied on the next push (F13).
- "Conversation context" block in the note shows the last 3 turns per
  recipient so the LLM stops repeating itself across pushes.

## Where each feature lands in `docs/code_structure.md`

- F11: `src/stock/action_queue.py` (new) under "Root files / src/stock";
  amended `research.py`, `cli.py`, `orchestrator.py`. New `action_queue` SQL
  table and `prompts/research.txt` updated.
- F12: `src/stock/anomaly.py` (new), `src/stock/holdings.py` (new),
  `src/stock/ingest/insiders.py` (new); new SQL tables `holdings`,
  `insider_filings`; `data/holdings.yaml`; new CLI `stock holding ...`.
- F13: `src/stock/conversation.py` (new); `conversation_embeddings` vec0
  virtual table + `conversations` SQL table; `_job_learn_from_feedback`
  added to orchestrator; new prompt `prompts/reply.txt` and
  `prompts/rewrite_prompt.txt`.

## Cost / budget impact

- F11: +1 deep-dive call per outstanding action item per cycle. With 2-4
  items/day and `MiniMax-M2.5-highspeed`, ~$0.01-0.02/day extra.
- F12: anomaly flagger is local-only. Holdings health-check runs weekly
  (one deep-dive per holding × 5–10 holdings) ~$0.06/week. Form 4 fetcher
  is free (SEC EDGAR no key).
- F13: classifier is MiniMax cheap call (~$0.001/inbound). Auto-rewrite
  uses Opus, gated to once/week unless `daily_cost_ceiling_usd` headroom
  permits more — reuse the `OPUS_BUDGET_THRESHOLD=$1.00` rule from `learn.py`.

Aggregate ceiling stays under the existing $0.50/day default — no change to
the kill switch.
