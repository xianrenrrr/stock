# Plan C — F13: Hermes-style Two-way Conversation Memory + Auto-rewrite

Goal: every WeChat exchange (boss reply -> our response) becomes a remembered,
embeddable, retrievable turn that feeds back into prompts and, when the boss
issues a directive, autonomously rewrites our prompt+rules.

## Schema additions (`src/stock/db.py`)

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,                 -- maps a Q->A round across direction rows
    recipient TEXT NOT NULL,              -- WeChat alias
    direction TEXT NOT NULL,              -- 'inbound' (boss) | 'outbound' (us)
    body TEXT NOT NULL,
    intent TEXT,                          -- 'question' | 'instruction' | 'ack' | 'unknown'
    intent_confidence REAL,
    related_research_id INTEGER REFERENCES research_reports(id),
    related_action_queue_id INTEGER REFERENCES action_queue(id),
    rewrite_id INTEGER,                   -- prompt_rewrites.id if instruction triggered one
    created_at TEXT NOT NULL,
    embedding_idx INTEGER                 -- mirror of conversation_embeddings.rowid
);
CREATE INDEX IF NOT EXISTS idx_conversations_recipient_created
    ON conversations (recipient, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_intent
    ON conversations (intent, created_at DESC);

CREATE TABLE IF NOT EXISTS prompt_rewrites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_path TEXT NOT NULL,            -- 'prompts/research.txt' | 'data/rules/current.md'
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    rationale TEXT NOT NULL,
    triggered_by_conversation_id INTEGER REFERENCES conversations(id),
    cost_usd REAL NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,   -- 0 = staged, 1 = applied
    applied_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_rewrites_applied
    ON prompt_rewrites (applied, created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_embeddings USING vec0(
    conversation_id INTEGER PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);
```

Reuses `case_embeddings`'s sqlite-vec pattern + 384-dim sentence-transformers
embedding, so no new model download.

## New file list with module-level docstrings

| Path                           | Module docstring                                                                  |
|--------------------------------|-----------------------------------------------------------------------------------|
| `src/stock/conversation.py`    | `"""stock.conversation -- two-way WeChat conversation memory with vector recall."""` |
| `src/stock/intent.py`          | `"""stock.intent -- classify inbound WeChat messages into question / instruction / ack."""` |
| `src/stock/prompt_rewriter.py` | `"""stock.prompt_rewriter -- Opus-driven editing of prompts/research.txt + data/rules/current.md."""` |
| `prompts/intent_classify.txt`  | `[SYSTEM]/[USER]` template; outputs `{intent, confidence, summary}` JSON.        |
| `prompts/reply.txt`            | `[SYSTEM]/[USER]` template for question-answering replies.                       |
| `prompts/rewrite_prompt.txt`   | `[SYSTEM]/[USER]` template for the Opus rewriter; outputs `<patch>` blocks.      |

## `src/stock/conversation.py` public surface

- `class ConversationTurn(BaseModel)` mirrors a row.
- `record_inbound(recipient, body, conn, *, related_research_id=None) -> int`
  — generate `run_id = uuid4()`, persist + embed.
- `record_outbound(recipient, body, conn, *, run_id, related_research_id=None,
  related_action_queue_id=None) -> int` — joins same run_id.
- `retrieve_similar(query_embedding, conn, *, recipient=None, k=5)
  -> list[ConversationTurn]` — vec0 KNN, optional recipient filter.
- `recent_turns(conn, *, recipient, limit=6) -> list[ConversationTurn]`
  — last N by `created_at DESC`, used for prompt context block.
- `format_context_block(turns) -> str` — for `{conversation_context_block}`
  in `prompts/research.txt`.

Embedding: same `stock.memory.embed()` reused; serialize via
`_serialize_embedding`. Embedding write: `INSERT INTO conversation_embeddings`
under same conn; mirror `embedding_idx` back into the row.

## `src/stock/intent.py` public surface

- `class IntentResult(BaseModel)` — `intent`, `confidence`, `summary`,
  `suggested_topic` (for instructions referencing a ticker).
- `classify(text: str, *, recipient: str, conn) -> IntentResult` — calls
  MiniMax cheap model with the `intent_classify.txt` prompt; uses 200 input
  + 100 output tokens; ~$0.0001/call.
- Cost ceiling enforced via `check_cost_ceiling`; failure modes return
  `IntentResult(intent="unknown", confidence=0.0)` rather than raising.

## `src/stock/prompt_rewriter.py` public surface

- `class RewriteProposal(BaseModel)` — `target_path`, `before_text`,
  `after_text`, `rationale`, `cost_usd`.
- `propose_rewrite(conversation_ids: list[int], conn) -> list[RewriteProposal]`
  — gathers the boss's instruction-typed turns (and our prior responses for
  context), reads the *current* file content, calls Claude Opus with the
  `rewrite_prompt.txt` template; expects output as 1-N `<patch>...</patch>`
  blocks each containing `<target>`, `<before>`, `<after>`, `<rationale>`.
  Refuses to apply if cost ceiling won't accommodate Opus — falls back to
  MiniMax-M1-80k with a `low_confidence=true` flag.
- `apply_rewrite(proposal, conn, *, dry_run=False) -> int | None` — writes
  the file, inserts `prompt_rewrites` row with `applied=1`. Always keeps
  the `before_text` so we can revert. Returns the `prompt_rewrites.id`.
- `revert_rewrite(rewrite_id, conn)` — file restore + audit row.

Safety rails:
- Only allowed targets: `prompts/research.txt`, `data/rules/current.md`,
  `prompts/intent_classify.txt`, `prompts/reply.txt`. Any other path
  rejected.
- File diff size cap: refuse `after_text` longer than `2 *
  len(before_text) + 2000 chars`.
- Rate-limit auto-applies to once per 24h per file.

## New job: `_job_learn_from_feedback()`

Fires 5 minutes after each push-cycle (i.e. 02:35 and 14:35 UTC).
Pseudo-code in `orchestrator.py`:

```python
def _job_learn_from_feedback() -> None:
    conn = get_conn()
    try:
        # 1. Read fresh inbound entries written since last run
        new_inbounds = wechat_inbox.read_feedback_entries(lookback_days=1)
        recorded_ids: list[int] = []
        for entry in new_inbounds:
            if conversation.has_entry(conn, entry.timestamp, entry.recipient):
                continue
            inbound_id = conversation.record_inbound(
                entry.recipient, entry.text, conn,
            )
            intent_result = intent.classify(entry.text, recipient=entry.recipient, conn=conn)
            conversation.set_intent(conn, inbound_id, intent_result)
            recorded_ids.append(inbound_id)

            if intent_result.intent == "question":
                reply_body = generate_reply(entry, intent_result, conn)
                wechat.send_message(entry.recipient, reply_body, conn)
                conversation.record_outbound(
                    entry.recipient, reply_body, conn,
                    run_id=conversation.get_run_id(conn, inbound_id),
                )
            elif intent_result.intent == "instruction":
                queued = action_queue.enqueue_actions(
                    conn, source_research_id=None,
                    raw_items=[intent_result.suggested_topic or entry.text],
                )

        # 2. After all inbounds handled, batch any instruction-typed turns
        instruction_ids = conversation.recent_instruction_ids(conn, hours=12)
        if instruction_ids:
            proposals = prompt_rewriter.propose_rewrite(instruction_ids, conn)
            for proposal in proposals:
                prompt_rewriter.apply_rewrite(proposal, conn)
    finally:
        conn.close()
```

`generate_reply()` is a thin wrapper that:
- Builds `{conversation_context_block}` for the recipient.
- Pulls `retrieve_similar()` k=5 from past conversations.
- Pulls latest `research_reports` body for the recipient as context.
- Calls MiniMax with `prompts/reply.txt` → returns plain text.
- Caps body at 600 chars and ensures `Not financial advice.` suffix.

## Prompt extension (`prompts/research.txt`)

Add a new section above "Reader feedback":

> ## Conversation context (last 3 turns per recipient)
> {conversation_context_block}

Block formatter (`format_context_block`) emits:

```
- [recipient: 杨建中]
  - [2026-04-27 22:15] them: "再写短一些，多看A股"
  - [2026-04-28 02:30] us: "好，今晚改为 1500 字以内并把焦点放在..."
  - [2026-04-28 02:31] them: "👍"
```

## Dependencies

- F11 `action_queue` table + `enqueue_actions()` — F13 instruction-handling
  fans out into the same queue rather than reinventing.
- F12 `holdings` table — when the boss says "how is my portfolio?"
  intent=question, the reply generator pulls `format_holdings_block` to
  ground the answer.
- `wechat_inbox.read_feedback_entries` for ingest — F13 supersedes the
  manual `stock add-feedback` workflow but does not remove it (the CLI
  remains a fallback for OCR-failure cases).

## Scheduler timing

Added one job:

```python
# Learn-from-feedback fires 5 min after each push so the boss has had time
# to type a reply between the push (02:30) and the screenshot pull (02:20)
# of the *next* cycle. We pick up replies from the last 24h.
scheduler.add_job(
    _job_learn_from_feedback,
    CronTrigger(
        hour=f"{RESEARCH_MORNING_HOUR},{RESEARCH_EVENING_HOUR}",
        minute=35, timezone="UTC",
    ),
    id="learn_from_feedback",
    name="Classify replies, queue follow-ups, auto-rewrite prompt",
)
```

The classifier runs ~10/day max; rewrites are gated to once per 24h per file.

## Prompt rewrite mechanics

The Opus rewriter prompt (`prompts/rewrite_prompt.txt`) emits something like:

```
<patch>
  <target>prompts/research.txt</target>
  <before>Keep the whole note under {max_chars} characters total</before>
  <after>Keep the whole note under 1500 characters total</after>
  <rationale>Boss asked for shorter notes on 2026-04-27</rationale>
</patch>
```

`apply_rewrite()` finds the *exact* `before_text` substring and replaces it
once. If `before_text` not found verbatim, the proposal is staged
(`applied=0`) and surfaced via API for human review — never silently
"close enough" matched. This guarantees byte-exact, auditable edits.

## Cost ceiling impact

| Op                        | Freq        | Tokens (in+out) | Cost/run    |
|---------------------------|-------------|-----------------|-------------|
| Intent classify           | 5/day       | 200+100         | $0.00007    |
| Reply generation          | 3/day       | 1500+400        | $0.0006     |
| Embedding (local)         | 8/day       | n/a             | $0          |
| Conversation context block| 0 (in research push) | folded into existing budget | $0 |
| Opus prompt rewrite       | <=1/day     | 4000+1000       | $0.135      |
| MiniMax fallback rewrite  | <=1/day     | 4000+1000       | $0.0024     |

Daily-spend impact under the typical case: $0.001-0.005/day.
Worst case with one Opus rewrite: $0.14. The Opus path is gated by
`OPUS_BUDGET_THRESHOLD = 1.0` and the existing daily $0.50 ceiling — never
fires unless headroom exists.

## Time estimate

- Session 1 (~3h): schema + `conversation.py` + tests; embedding wiring.
- Session 2 (~3h): `intent.py` + `prompts/intent_classify.txt` +
  `prompts/reply.txt` + reply generation; fold into orchestrator.
- Session 3 (~3h): `prompt_rewriter.py` + Opus integration + CLI/API
  surface for staged rewrites; tests; rollout flag.

Total: ~9h, 3 sessions.

## Test plan

- `test_conversation.py`:
  - record inbound + outbound: same `run_id`; both have `embedding_idx`
    after the call.
  - `retrieve_similar` filters by recipient when given.
  - `recent_turns(limit=6)` ordering correct.
  - `format_context_block` truncates each turn body to 240 chars.
- `test_intent.py`:
  - With mocked LLM returning each of `{question, instruction, ack,
    unknown}` JSON shapes, classifier returns matching `IntentResult`.
  - Cost-ceiling raises -> classifier returns `intent="unknown"`.
- `test_prompt_rewriter.py`:
  - `propose_rewrite` honors target whitelist.
  - `apply_rewrite` succeeds only on exact substring match; mismatch
    stages with `applied=0`.
  - Diff-size cap enforced.
  - Revert restores the original file.
- `test_orchestrator.py` extension:
  - `_job_learn_from_feedback` with mocked classifier handles all four
    intents and writes the right tables.

## Risks / mitigations

- **OCR / transcription gap** — `_job_learn_from_feedback` currently
  reads from `data/wechat_feedback.md` which is operator-edited. If
  empty, the job is a no-op. Vision-LLM ingest is out of scope here
  but the schema makes adding it trivial (new `source` value).
- **Auto-rewrite drift** — every rewrite is logged in `prompt_rewrites`
  with full before/after; `stock prompt revert <rewrite_id>` rolls back.
  Manual review surface via `GET /stock/prompt_rewrites?applied=0`.
- **Embedding model load** — first call hits sentence-transformers; the
  module caches it (already done in `stock.memory`). The first
  feedback-job after start will be slow (~5s); subsequent <100ms.
- **WeChat reply storms** — the reply generator runs at most 1x per
  inbound per cycle; an `intent="ack"` (likes/emoji) does not trigger
  a reply.
- **Privacy** — `data/wechat_feedback.md` and `conversations.body`
  contain personal text. Already excluded via `.gitignore` for `data/`.
