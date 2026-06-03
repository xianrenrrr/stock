# Prediction Rules v003

## Objective And Horizon
- Predict only the next trading session’s close-to-close direction.
- `prob_up` is the probability that the stock closes higher next session.
- `prob_up > 0.50` is an up prediction. `prob_up < 0.50` is a down prediction.
- If the same ticker/session has duplicate opposite-direction predictions, merge them into one prediction before scoring or publishing; when the merged up/down probability gap is below `0.04`, force the final `prob_up` back to neutral `0.50-0.51`.
- Do not use catalysts whose expected impact is mainly quarterly, annual, or strategic unless they plausibly change next-session positioning.
- Capital rule: never recommend borrowing money, margin, leverage, cash advances,
  portfolio margin, or any trade requiring debt. Use available cash only and
  preserve a cash reserve before new buys.

## Evidence Hierarchy
1. Rank evidence in this order:
   - Fresh earnings, guidance, revenue, margin, dividend, buyback, contract, order, regulatory approval/order, or confirmed financial impact.
   - Same-day market reaction to that hard catalyst.
   - Direct peer earnings/guidance read-through.
   - Sector breadth and leader direction.
   - Stock-specific price action and volume.
   - Macro/rates/futures/geopolitical backdrop.
   - Analyst notes, institutional-positioning headlines, product launches, partnerships, listicles, and AI/theme articles.
2. A product launch, partnership, MOU, index inclusion, analyst target hike, or “AI beneficiary” article is not a hard catalyst unless it includes explicit near-term revenue, order size, margin, guidance, or regulatory financial impact.
3. Political-trading disclosures, congressional/executive portfolio headlines, and ethics/timing controversy are soft headline-risk inputs only unless a filing or regulator confirms insider-trading evidence; after the related contract or award is already public and the stock has repriced, treat the setup as chase risk rather than a buy catalyst.
4. Duplicate articles about one event count once. Do not raise probability or confidence because multiple headlines repeat the same catalyst.

## Fresh Hard Catalysts
1. Treat fresh hard catalysts as active for three trading sessions, with decay:
   - Day 0-1: primary signal.
   - Day 2-3: secondary signal.
   - After day 3: background only.
2. If a fresh hard positive catalyst arrives after the latest close and has not yet traded in the regular session, start from `prob_up = 0.55`.
3. If that catalyst is company-specific and measurable, allow `0.56-0.61` when price action, volume, or sector also confirms.
4. If the stock already traded after the catalyst and then closed in the bottom 25% of its range or below the open, classify as `post-catalyst fade`; cap `prob_up` at `0.50`.
5. Fresh earnings/guidance beats worked when not yet faded or when price confirmed, such as SMTC and MRVL. Failed post-catalyst reactions worked better as fades, such as SMTC after its gap-up reversal.
6. For post-earnings day-2 setups, model continuation separately from exhaustion using first-day reaction size, gap magnitude, close location, next-day premarket action, peer breadth, and volume; if the first-day earnings reaction was already above 8%-10% and there is no new information on day 2, cap `prob_up` at `0.52` unless same-group leader direction and volume continue to confirm.

## Sector Breadth Override
1. For semiconductors, memory/storage, AI servers, AI infrastructure, optical networking, and data-center power names, calculate same-group breadth from the prior session.
2. If at least 65% of same-group peers closed up and at least one sector leader or direct peer closed non-negative, do not assign `prob_up < 0.50` to AI-infrastructure, optics, or semiconductor names unless there is a fresh company-specific negative hard catalyst.
3. When a DELL, SMCI, NVDA, MRVL, CRDO, or COHR-level hard catalyst is confirmed and same-group AI-infrastructure or optics breadth is supportive, do not assign `prob_up < 0.50` to AAOI, CRWV, LITE, COHR, CIEN, CAMT, ACMR, AOSL, CORZ, or NBIS unless there is a fresh company-specific negative hard catalyst.
3. A failed gap-up, bottom-quartile close, or reversal-down tag does not defeat this override by itself.
4. To make a down call below `0.49` in a supportive-breadth tape, require at least two of:
   - Fresh company-specific negative hard catalyst.
   - Downside volume at least 1.5x recent average.
   - Stock underperformed its peer group by at least 3 percentage points.
   - Sector leader closed down.
5. This rule addresses repeated missed down calls in AMAT, AMD, AVGO, LRCX, MU, TSM, SNDK, and ORCL when broad sector demand outweighed weak intraday candles.

## Price Action Rules
1. A close in the top 25% of the daily range is bullish only if close-to-close direction is also positive or the stock reversed from a multi-session selloff.
2. A close in the bottom 25% of the daily range is bearish only if close-to-close direction is also negative or the stock failed a gap-up.
3. A failed gap-up means: open above prior close, intraday high above open, and close in the bottom half of the range. This supports a down call only when sector breadth is not strongly supportive.
4. A failed gap-up on elevated volume after an extended rally is a strong fade setup. Allow `prob_up = 0.43-0.47`.
5. A reversal up after a selloff is valid only when the stock is not already extended up and volume is neutral or better. Otherwise cap at `0.52`.
6. Do not treat a single strong close as enough for an up call when all news is stale/thematic and the stock has already gained more than 8% in three sessions.

## Extension And Mean Reversion
1. A stock is `extended up` if it gained more than 8% over three trading sessions or more than 15% over five sessions.
2. A stock is `extended down` if it lost more than 6% over three trading sessions or more than 12% over five sessions.
3. Extension alone is not a directional signal. It only caps continuation probability unless paired with failed price action.
4. For extended-up stocks with no fresh hard catalyst:
   - If top-quartile close and volume confirms, keep `prob_up` in `0.51-0.54`.
   - If weak close or failed gap-up, use `0.45-0.49`.
   - If sector breadth is strongly supportive, use `0.49-0.53`.
5. For extended-down stocks with no fresh negative catalyst:
   - Do not assign `prob_up < 0.49` when sector breadth is mixed or supportive.
   - If intraday action recovers into the upper half of the range after a selloff, use `0.51-0.53`.
   - If close is top-quartile after a selloff, use `0.51-0.54`.
6. Extreme extension in A-share/HK names is more fade-prone. If a stock is up more than 12% over 2-5 sessions with no same-day hard catalyst, cap any up call at `0.51`; if it also fails intraday or volume fades, prefer down `0.45-0.49`.

## Stale Narrative Trap
1. If the rationale is mainly AI demand, data-center demand, analyst support, institutional interest, China localization, product positioning, or long-term TAM, cap `prob_up` at `0.54`.
2. If stale bullish narrative combines with weak price action, prefer down `0.45-0.49`.
3. If stale bullish narrative combines with supportive sector breadth and constructive price action, prefer only a modest up call `0.51-0.54`.
4. Do not short stale narratives aggressively when the whole peer group is rising.

## Analyst, Institutional, And Product Signals
1. Analyst target hikes, top-pick calls, valuation articles, institutional stake headlines, and index inclusion are secondary sentiment inputs only.
2. Cap their probability impact at 2 percentage points.
3. Product and partnership announcements without disclosed financial scale are treated the same as analyst signals.
4. A fresh product headline plus top-quartile close may justify `0.51-0.53`, but not above `0.53`.

## Peer Read-Throughs
1. Use peer read-throughs only when the business linkage is direct:
   - Memory/storage: MU, WDC, STX, SNDK.
   - AI servers: DELL, SMCI.
   - Semicap equipment: AMAT, ASML, KLAC, LRCX.
   - AI connectivity/optics: CRDO, COHR, LITE, AAOI.
2. Peer-read-through-only predictions are capped at `0.55`.
3. If peer read-through, price action, and sector breadth all agree, allow `0.53-0.56`.
4. If peer read-through conflicts with the target stock’s strong opposite price action, keep probability within `0.48-0.52`.

## Macro And Sector Regime
1. Macro alone should rarely move `prob_up` outside `0.44-0.56`.
2. Macro is actionable only when at least two of these align:
   - Higher Treasury yields.
   - Hot inflation or hawkish Fed signal.
   - Weak futures or broad tech selloff.
   - Geopolitical/export risk.
   - Sector leader weakness.
3. If macro and price action agree, use `0.44-0.47` or `0.53-0.56`.
4. If macro conflicts with strong company-specific hard news, hard news wins unless the stock fades the catalyst during regular trading.

## Volume
1. Elevated volume confirms the direction of a breakout, breakdown, failed gap-up, or post-earnings reaction.
2. Low or uncertain volume caps confidence at `0.48`.
3. Low-volume top-quartile closes after extended rallies must not receive `prob_up > 0.52`.
4. Elevated downside volume after a failed gap-up allows stronger bearish calls than price action alone.
5. Elevated upside volume after a hard catalyst allows stronger bullish calls unless the close is bottom-quartile.

## Probability Calibration
1. Default to `0.50` when evidence is mixed, duplicated, stale, thematic, or low-volume.
2. Use `0.51-0.54` for price-action-only or sector-only bullish edges.
3. Use `0.46-0.49` for weak price action, stale bullish narrative, or post-rally fade setups.
4. Use `0.55-0.61` only when a fresh hard catalyst and at least one confirming signal align.
5. Use `0.42-0.45` only for failed gap-up or breakdown setups with elevated downside volume and no supportive sector override.
6. Do not use probabilities above `0.62` or below `0.38` unless there is an exceptional event: takeover, fraud, accounting issue, guidance withdrawal, regulatory ban, major contract, or severe earnings shock.
7. Review evidence showed routine `0.55+` calls on soft catalysts were too aggressive. Soft-catalyst predictions must remain below `0.54`.
8. For small contract, order, partnership, or policy headlines with low disclosed dollar value, no guidance change, and an already extended-up stock, prohibit `prob_up >= 0.55`; cap at `0.52`, and if continuation has already failed, use `0.48-0.50`.

## Confidence Calibration
1. Confidence measures signal quality, not conviction.
2. Assign confidence above `0.55` only when at least three independent signals agree:
   - Fresh hard catalyst.
   - Confirming price action.
   - Confirming volume.
   - Supportive sector breadth or macro.
3. Confidence above `0.60` requires a fresh hard catalyst plus confirming price and volume.
4. If rationale includes stale, repeated, thematic, indirect, mixed, low-volume, or uncertain evidence, cap confidence at `0.50`.
5. Confidence did not reliably predict accuracy in this review period; do not raise confidence for familiar tickers or repeated similar-case patterns alone.

## Required Checklist
Before issuing a prediction, classify each item explicitly:

1. Fresh hard catalyst: `positive`, `negative`, or `none`.
2. Catalyst state: `untraded`, `confirmed`, `faded`, `stale`, or `duplicated`.
3. News novelty: `fresh`, `repeated`, `stale`, or `thematic`.
4. Price action: `confirming up`, `confirming down`, `reversal up`, `reversal down`, or `mixed`.
5. Extension: `extended up`, `extended down`, or `not extended`.
6. Sector breadth: `supportive`, `hostile`, or `mixed`.
7. Volume: `confirming`, `low/uncertain`, or `neutral`.
8. Final override: `hard catalyst`, `sector breadth`, `post-catalyst fade`, `extension fade`, `oversold rebound`, or `none`.

Only move probability more than 3 points from neutral when at least two independent checklist items point the same way.

## Common Failure Modes To Avoid
1. Do not short a whole supportive semiconductor or AI-infrastructure tape because one stock closed off its high.
2. Do not chase A-share/HK parabolic rallies on stale thematic news.
3. Do not assign `0.55+` to product, partnership, analyst, or AI-narrative headlines.
4. Do not treat extension alone as bearish when price, volume, and sector breadth still confirm up.
5. Do not treat hard positive catalysts as bullish after the stock has already failed the catalyst intraday.
6. Do not press downside after multi-day selloffs without fresh negative news.
7. Do not raise confidence when the rationale itself says evidence is stale, duplicated, indirect, or low-volume.

## Calibration Review Targets
- Keep most routine predictions between `0.46` and `0.54`.
- Use `0.55+` sparingly and only for fresh hard catalysts with confirmation.
- Track misses by category:
  - Sector-breadth override miss.
  - Stale narrative chase miss.
  - Failed-gap false negative in supportive tape.
  - Extension fade miss.
  - A-share/HK parabolic continuation miss.
  - Soft-catalyst overconfidence miss.
- Revise rules only when the same miss category appears at least three times in the review window.
