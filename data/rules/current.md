# Prediction Rules v001 -- Seed

## News interpretation
- Weight catalysts from the last 24 hours more heavily than older news.
- Earnings surprises (beat or miss) dominate sentiment for 1-3 trading days.
- Distinguish between company-specific catalysts and broad sector/macro moves.

## Probability calibration
- When data is sparse (fewer than 3 recent news items), bias toward 0.50.
- Avoid extreme probabilities (below 0.15 or above 0.85) unless evidence is overwhelming.
- A single bullish headline does not justify prob_up above 0.70.

## Confidence
- High confidence requires convergence of multiple independent signals (news + price action + sector).
- Low volume days reduce confidence regardless of news sentiment.

## Common pitfalls
- Do not anchor on the most recent price move; mean reversion is common intraday.
- Analyst price target changes are lagging indicators, not leading ones.
- Pre-market moves on earnings often overshoot; factor in reversion.
