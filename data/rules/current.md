# Prediction Rules v004

## Objective And Horizon
- Predict only the next trading session’s close-to-close direction.
- `prob_up` is the probability that the stock closes higher next session.
- `prob_up > 0.50` is an up prediction. `prob_up < 0.50` is a down prediction.
- If duplicate same-ticker/session predictions disagree and the averaged directional gap is below `0.04`, force final `prob_up` to `0.50-0.51`.
- Do not use quarterly, annual, strategic, or long-dated narratives unless they plausibly change next-session positioning.
- Never recommend margin, leverage, borrowing, cash advances, or trades requiring debt.

## Evidence Hierarchy
1. Rank evidence in this order:
   - Fresh company-specific earnings, guidance, IPO/secondary-offering liquidity drain, lock-up supply, offering/dilution, contract/order size, regulatory order/approval, financing, buyback/dividend, or confirmed financial impact.
   - Regular-session reaction to that catalyst.
   - Direct peer earnings/guidance read-through.
   - Broad market, sector ETF, and sector-leader regime.
   - Stock-specific price action and volume.
   - Macro/rates/futures/geopolitical backdrop.
   - Analyst notes, product launches, partnerships, listicles, institutional-positioning headlines, and theme articles.
2. Product launches, partnerships, MOUs, conferences, index chatter, analyst target hikes, “AI beneficiary” articles, and political-trading headlines are soft inputs unless they include disclosed near-term revenue, order size, margin, guidance, dilution, or regulatory financial impact.
3. Duplicate articles about one event count once.
4. A stale positive narrative plus a strong candle is not a fresh catalyst.

## Hard Catalyst Rules
1. A hard catalyst is active for three trading sessions:
   - Day 0-1: primary signal.
   - Day 2-3: secondary signal.
   - After day 3: stale/background.
2. For a fresh untraded positive hard catalyst, start at `prob_up = 0.54`.
3. Allow `0.55-0.60` only if:
   - Catalyst is company-specific and measurable.
   - Regular-session or premarket price action confirms.
   - Volume is at least `1.2x` recent average or sector breadth confirms.
4. If a positive catalyst has already traded and the stock closes below the open or in the bottom 40% of the range, classify as `post-catalyst fade`; cap `prob_up` at `0.50`.
5. If a stock gained more than `8%` on day 0-1 after a positive catalyst and there is no new after-close measurable update, cap continuation at `0.51`; prefer `0.47-0.50` if the next session closes weak.
6. Fresh negative catalysts with confirmed weak price action are the most reliable short signal. Use `prob_up = 0.44-0.48` for:
   - Secondary offerings, resale registrations, insider-selling offerings, or dilution.
   - Earnings beats that sell off on guidance, margin, AI-outlook, or expectation disappointment.
   - Peer earnings/guidance that directly damages the thesis.
   - Regulatory or legal events with plausible near-term financial impact.
7. If a fresh negative catalyst is already followed by an extended-down move, do not go below `0.44` unless volume is extreme and sector/macro is also hostile.
8. Dilution decay: once a negative offering/dilution catalyst enters day 2-3 and the stock is already `extended down`, floor `prob_up` at `0.48` and cap confidence at `0.50`; the easy move has traded and squeeze risk dominates (PL/SMCI day-2/3 short pattern went 0/2).

## Soft Catalyst Rules
1. Soft-catalyst-only predictions must stay in `0.48-0.52`.
2. A soft positive headline plus top-quartile close may justify only `0.51-0.52`.
3. A soft positive headline plus extension up or low volume must not justify `prob_up > 0.51`.
4. Analyst target hikes, top-pick calls, product PR, conference participation, partnerships without financial scale, and listicles may move probability by at most 1 point.
5. Do not assign `0.53+` unless there is either a fresh hard catalyst or strong sector breadth plus confirming price and volume.
6. If news is stale/thematic and the latest close is weak, prefer `0.47-0.49`.
7. If there is no fresh hard catalyst and the up-call rationale depends on stale/thematic, low-volume, or reversal-up evidence, default final `prob_up` to `0.49-0.50` unless at least two same-group breadth checks are positive: same-group median, sector ETF, or direct leader.

## Price Action
1. A top-quartile close is bullish only when close-to-close direction is positive and volume is at least neutral.
2. A low-volume top-quartile close after a selloff is only a stabilization signal; cap at `0.51`.
3. A bottom-quartile close is bearish only when close-to-close direction is negative or the stock failed a gap-up.
4. A failed gap-up means: open above prior close, intraday high above open, and close below open or in the bottom half of the range.
5. Failed gap-up with no fresh hard catalyst is a hard gate against an up call; use `0.47-0.50`, and only move below `0.47` when downside volume or hostile breadth confirms:
   - `0.47-0.50` on neutral volume.
   - `0.44-0.47` if volume is at least `1.5x` average and sector breadth is not supportive.
   - Washout-day hard gate: if the PRIOR session was a broad washout session (sector ETF/leaders broadly down), force `prob_up` for ANY down call with no fresh negative hard catalyst to `0.50-0.51` on the next session; the washout-day failed gap-up signal expires after that session and cannot justify a down call on its own.
6. A single strong close after stale news does not override extension, weak macro, or a recent post-catalyst fade.

## Extension And Mean Reversion
1. `extended up`: gain above `8%` over 3 sessions or above `15%` over 5 sessions.
2. `extended down`: loss below `-6%` over 3 sessions or below `-12%` over 5 sessions.
3. Extension alone is not a signal; extension plus weak price action is.
4. Extended-up, no fresh hard catalyst:
   - Strong close and confirming volume: `0.50-0.52`.
   - Weak close or failed gap-up: `0.46-0.49`.
   - Broad hostile tape: `0.45-0.48`.
5. Extended-down, no fresh negative hard catalyst:
   - Do not automatically predict rebound.
   - Use `0.51-0.52` only if the stock closes top-quartile and volume is at least neutral.
   - If rebound volume is low/uncertain, stay `0.49-0.51`.
   - If broad market or same-group tape is hostile, do not use oversold rebound above `0.51`.
6. For A-share/HK/Asia parabolic moves:
   - If up more than `12%` in 2-5 sessions with no same-day hard catalyst, cap up calls at `0.51`.
   - If it then closes below open, below prior close, or on fading volume, prefer `0.47-0.49`.
   - Do not use low-volume “near-high” closes as continuation signals after parabolic moves.
   - Strong-breadth exception (Asian/A-share semis): when US/global semi breadth is strongly up (e.g. SOXX up more than `3%`) and the parabolic name has no fresh same-day negative hard catalyst, apply the Sector §8 short suppression even if a same-group Asian median/leader breadth reading is unavailable — force `prob_up >= 0.50` instead of fading the parabola. Treat the strongly-up US semi tape as sufficient supportive breadth for Asian semiconductors, which squeeze hardest on these days.

## Sector And Peer Breadth
1. Sector breadth can prevent an aggressive contrarian call, but it cannot by itself justify a bullish call above `0.52`.
2. Use sector breadth only when at least two are known:
   - Same-group median return.
   - Sector ETF return.
   - Direct leader return.
   - Direct peer earnings/guidance read-through.
3. Supportive semiconductor, AI-infrastructure, optics, memory, or data-center tape may floor bearish calls at `0.48` unless:
   - The stock has a fresh negative hard catalyst.
   - The stock failed a gap-up on elevated volume.
   - A direct leader or peer reported a negative read-through.
   - The broad market/sector ETF is hostile.
4. Disable the bullish sector-breadth override during hostile regime sessions where sector leaders, futures, or ETFs are broadly down.
5. Direct peer read-through is actionable only when the business linkage is clear:
   - Memory/storage: MU, WDC, STX, SNDK.
   - AI servers: DELL, SMCI, HPE.
   - Semicap equipment: AMAT, ASML, KLAC, LRCX, ONTO, CAMT.
   - Optics/connectivity: CRDO, COHR, LITE, AAOI, CIEN.
   - AI data-center power: VRT, ETN, GEV, VST, CEG.
6. Negative peer earnings reactions, such as AI outlook disappointment, override stale bullish sector narratives for one session only when at least two breadth indicators are hostile or the same-subsegment linkage is explicit and confirmed.
7. A single negative peer read-through, including Broadcom-style AI outlook commentary, cannot push `prob_up` below `0.49` unless at least two breadth indicators are hostile; otherwise cap at `0.49-0.51`.
8. Strong-breadth short suppression: when at least two breadth indicators are STRONGLY positive (for example a sector ETF such as SOXX up more than `3%`, same-group median strongly up, or a direct leader strongly up) and the stock has NO fresh negative hard catalyst, force `prob_up >= 0.50` for any down call. This override supersedes the failed-gap-up gate (Price Action §5) and the parabolic/extension-fade gate (Extension §6); under supportive breadth those bearish gates invert (12/12 down-calls wiped out on a +4.4% SOXX day from failed-gap/parabolic-exhaustion reasoning). When this strong-breadth override is the SOLE basis for lifting a call to `prob_up >= 0.50` and there is NO fresh positive hard catalyst, cap final `prob_up` at exactly `0.50` (pure neutral, not `0.51`); if the suppressed name itself shows a same-day failed gap-up or volume exhaustion, allow `prob_up = 0.49`. Override-suppressed up-calls hit only ~35%, so the override prevents the short but does not justify a positive tilt.

## Macro And Regime
1. Macro alone should keep probabilities inside `0.47-0.53`.
2. Macro becomes actionable when at least two align:
   - Weak index futures or broad tech selloff.
   - Higher yields or hawkish rates news.
   - Geopolitical risk-off.
   - Sector ETF/leader weakness.
   - Direct peer selloff.
3. In a hostile macro/sector regime, do not issue soft-catalyst up calls above `0.51`.
4. In a hostile macro/sector regime plus confirming down price action, use `0.45-0.48`.
5. Exogenous macro/geopolitical one-off events (e.g. Iran peace, sanctions or oil-shock headlines) provide at most ONE trading session of directional breadth support. From the second session onward, force any up-call whose bullish rationale depends SOLELY on such an event to `prob_up = 0.49-0.50`. Geopolitical-catalyst calls hit only ~30% (16/23 wrong), driven by day-2+ continuation bets.

## Volume
1. Elevated volume confirms the direction of a breakout, failed gap-up, breakdown, or post-catalyst reaction.
2. Low/uncertain volume caps `prob_up` between `0.49-0.51` unless a fresh hard catalyst exists.
3. Low-volume reversal-up after selloff is not enough for an up call above `0.51`.
4. Low-volume continuation after an extended rally should be treated as exhaustion risk.
5. Elevated downside volume after a failed gap-up supports `0.44-0.47`.

## Probability Calibration
0. Use raw `prob_up` for decisions, reporting, final direction selection, and display; keep the current calibrated output fully disabled until separate up-call/down-call calibration variants beat raw Brier on holdout across at least 3 scored sessions.
1. Most predictions should be `0.47-0.53`.
2. Use `0.51-0.52` for modest price-action or sector-only bullish edges.
3. Use `0.47-0.49` for stale narrative plus weak price action.
4. Use `0.44-0.47` only when hard negative catalyst, failed gap-up, hostile sector, or elevated downside volume align.
5. If fresh hard negative catalyst is `none` and preliminary `prob_up` is `0.46-0.49` only because of confirming down price action, hostile sector, or stale/thematic narrative, move final `prob_up` back to `0.50-0.51` unless there is confirming downside volume or at least two same-group breadth indicators (median, ETF, direct leader) are also down.
6. Direction-specific guardrail: for low-confidence, near-neutral down calls with no hard catalyst, lift `prob_up` by 1-2 points before finalizing; only keep the down direction when at least two of price action, volume, and sector breadth point down.
7. Use `0.55+` only for fresh measurable hard catalysts with confirmation and no extension/fade warning.
8. Never use `0.55+` for stale AI, product, analyst, partnership, index, or theme headlines.
9. If evidence is mixed, stale, duplicated, low-volume, or conflicting across retrieved cases, force `0.49-0.51`.
10. Direction-concentration gate: when more than `70%` of the current session's calls across the universe point the same direction, force any marginal same-direction call with `|prob_up - 0.50| < 0.04` to `0.50`. When the concentrated direction is UP, a marginal bullish call in this band that ALSO shows a same-day bearish confirmation (failed gap-up or volume exhaustion) may be set to `0.49` rather than `0.50` — trend-cohort hit-rate decayed 47.7% → 35.7%, so over-concentrated bullish tapes warrant a slight reverse tilt.
11. Mean-reversion broad-up regime gate: when the sector ETF is up more than `3%` AND more than `70%` of the universe closed green, treat the tape as a mean-reversion broad-up regime and force `prob_up` to `0.50-0.51` for ANY down call lacking a fresh same-day negative hard catalyst. This supersedes the failed-gap-up and parabolic/extension-fade gates the same way Sector §8 does; counter-trend shorts were the dominant loss source on these days.

## Confidence Calibration
1. Confidence measures signal quality, not conviction.
2. Confidence above `0.55` requires:
   - Fresh hard catalyst.
   - Confirming price action.
   - Confirming volume.
3. Confidence above `0.60` is prohibited unless the catalyst is exceptional: takeover, fraud, guidance withdrawal, major dilution, regulatory ban, or severe earnings shock.
4. If rationale includes stale, thematic, duplicated, indirect, low-volume, or mixed evidence, cap confidence at `0.50`.
5. If confidence is `0.50` or lower and there is no fresh hard catalyst, compress final `prob_up` to `0.49-0.51`; directional calls require at least two of price action, volume, and sector breadth to agree.
6. Do not raise confidence for familiar tickers or retrieved similar cases alone; confidence did not reliably predict accuracy in this review period.

## Required Checklist
Before issuing a prediction, classify:

1. Fresh hard catalyst: `positive`, `negative`, `mixed`, or `none`.
2. Catalyst state: `untraded`, `confirmed`, `faded`, `stale`, or `duplicated`.
3. News novelty: `fresh`, `repeated`, `stale`, or `thematic`.
4. Price action: `confirming up`, `confirming down`, `reversal up`, `reversal down`, `failed gap-up`, or `mixed`.
5. Extension: `extended up`, `extended down`, or `not extended`.
6. Sector breadth: `supportive`, `hostile`, `mixed`, or `unknown`.
7. Volume: `confirming`, `neutral`, or `low/uncertain`.
8. Final override: `hard catalyst`, `post-catalyst fade`, `extension fade`, `oversold rebound`, `sector breadth`, `macro regime`, or `none`.

Only move probability more than 3 points from neutral when at least two independent checklist items point the same direction.

## Recurring Failure Modes To Avoid
1. Do not chase stale AI, optics, nuclear, rare-earth, space, or data-center narratives after a large top-quartile close.
2. Do not turn every extended-down stock into an up call; require volume or a strong close.
3. Do not let sector breadth override fresh negative catalysts or direct negative peer read-throughs.
4. Do not use `0.53+` for low-volume rebounds.
5. Do not chase day-2/day-3 post-earnings winners after a large first reaction unless a new measurable update appears.
6. Do not ignore failed gap-ups after parabolic rallies.
7. Do not raise confidence when the probability is near neutral.
8. Do not treat product launches or analyst notes as hard catalysts without financial scale.
