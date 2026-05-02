# Thesis-grading research stack (2024-2026)

Background reading that informed F16 (thesis tracking + verification). Read once, mine for ideas, do **not** vendor any of these libraries — most are too heavy for the 12 GB laptop and depend on external Google/Serper search. We re-implement the loops with our own evidence corpus + MiniMax.

## 1. Trading-R1 — Financial Trading with LLM Reasoning via RL
- Xiao, Sun, Chen, Wu, Luo, Wang. arXiv:2509.11420 (2025).
- Trains an LLM to emit a *typed thesis schema* (`strategic_thinking → facts_grounded_analysis → decision`), explicitly separating thesis composition from action so each layer can be supervised independently. SFT + RL on a 100k 18-month dataset; reports Sharpe 1.88 on NVDA, ~70% directional hit ratio.
- **What we steal:** The typed schema. Our `prediction_theses` table forces an LLM-written rationale to be decomposed into atomic, typed claims (`catalyst | valuation | technical | macro | sentiment`) so the *evidence layer* is scoreable post-hoc rather than the free-form blob we used to grade.

## 2. Synthesizing Behaviorally-Grounded Reasoning Chains
- Pan et al. FinNLP 2025.
- Generates training data where each prediction includes a behaviorally-grounded chain (news → behavioral hypothesis → price expectation), and uses *chain-consistency* as a training/eval signal alongside direction accuracy. Supervising the chain (not just the label) improves calibration and OOD stability.
- **What we steal:** A pre-verification chain-consistency check. Before the move is in, ask "does the rationale entail the predicted direction?" — disagreement flags "right direction wrong reason" without needing post-hoc news.

## 3. SAFE — Long-form factuality in LLMs
- Wei et al., DeepMind. arXiv:2403.18802 (2024). [github.com/google-deepmind/long-form-factuality](https://github.com/google-deepmind/long-form-factuality).
- Decomposes long-form output into atomic facts. For each fact, a search-agent loop runs `query → snippet → verdict (supported / refuted / irrelevant) → re-query if needed`. Aggregates with F1@K rewarding both precision and a target number of supported claims. 72% human agreement at 20× cheaper.
- **What we steal:** The exact verdict trichotomy (`supported | refuted | unverified`) and the per-claim search loop. We swap Google Search for our local news/insiders/anomaly DB plus optional Tavily — already wired via `stock.websearch` and `stock.webfetch`.

## 4. Claim Extraction for Fact-Checking — six metrics
- Ullrich, Mlynář, Drchal. arXiv:2502.04955 (2025). FEVERFact dataset.
- Defines six automatic metrics for claim-extraction quality: *atomicity, fluency, decontextualization, faithfulness* (per-claim) and *focus, coverage* (per-set). Each reduces to an existing NLP task so they compute without humans.
- **What we steal:** *Decontextualization* enforcement — every claim must stand alone (resolve "the company" → "AVGO"). Without this, downstream verification is garbage-in. Our `prompts/thesis_extract.txt` makes this an explicit rule.

## 5. Structured Event Representation and Stock Return Predictability
- Li, Qiao, Zheng. arXiv:2512.19484 (2025).
- LLM extracts typed event tuples `(actor, action, object, polarity, time)` from news, then an attention predictor runs over the structured stream. The structured layer makes per-event contributions to a return *traceable*.
- **What we steal:** When the move is in, run an *attribution pass* — extract structured events from the post-window news/filings and check whether the rationale's `key_factors` overlap with the events that actually moved the stock. Mismatch == "right direction wrong reason." This is the F16 grading insight.

## 6. Prophet Arena — calibration localization
- Yang et al. arXiv:2510.17638 (2025).
- Decomposes a probabilistic LLM forecast into `recall → aggregation → calibration` stages and logs metrics per stage so you can localize *where* the forecast goes wrong, not just measure ECE/Brier on the final number.
- **Deferred:** Worth doing as F17 — split the calibration regressor into recall vs aggregation vs final-prob. Out of scope for F16.

## Why we don't pip-install FActScore / FacTool / SAFE / FIRE / VeriFastScore
- Each ships its own retriever (Google / SERPER / spaCy `en_core_web_sm` ~50 MB) and assumes a generic web corpus. Our evidence is *finance-specific* — yfinance + RSS + insider Form 4 + Tavily — so a generic retriever would mostly miss.
- Combined deps add ~2 GB of model weights and pin older transformers/spaCy/torch. Not worth it on a 12 GB laptop also running OpenClaw + WeChat.
- We add **only `arxiv`** (~150 KB pure Python) so future sessions can `arxiv.Search(...)` for fresh papers programmatically without spinning up a new web search.

## Implementation map (F16)

| Paper idea | F16 surface |
|---|---|
| Typed thesis schema (Trading-R1) | `prediction_theses.claim_type` enum |
| Atomic claims + decontextualization (Ullrich, SAFE) | `prompts/thesis_extract.txt` |
| Search-and-verdict loop (SAFE) | `thesis.verify_thesis()` |
| Event-attribution post-mortem (Li 2025) | `thesis.verify_thesis` evidence pull = post-window news + price action |
| supported / refuted / unverified verdict trichotomy | `prediction_theses.verdict` enum |
| "Right direction wrong reason" surfacing | `thesis.compute_thesis_stats` + grading note section |

Not financial advice.
