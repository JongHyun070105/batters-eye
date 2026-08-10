# Simple Gap Decision Journal Policy

The live strategy remains deterministic. News, disclosures, and language-model opinions do not approve buy orders.

## Before an order

Every final candidate receives a structured memo before any order submission:

- the pre-registered low-volume gap mean-reversion hypothesis;
- observed gap, opening price, previous close, prior-volume ratio, and candidate rank;
- the continuing-selloff, corporate-action, price-basis, warning, liquidity, and quote-drift bear cases;
- the 2.25% stop, 12% take-profit, and 15:20 time exit;
- the 10,000 KRW position ceiling, one entry per day, 100% daily purchase-turnover ceiling, and no same-day re-entry rule. Turnover is measured as gross daily buy notional divided by maximum position capital; sells are excluded from this measure.

The memo write is part of the existing fail-closed entry audit. If the audit cannot be written, no new order is allowed.

## Candidates not selected

After the first executable candidate is selected, every remaining lower-ranked candidate is recorded as `not_selected_lower_rank`. These names are not re-quoted or warning-checked and never cause an order. Their outcome measures screening/ranking quality only; it is not evidence that the rejected trade was executable.

## After the close

Run after the official daily candles are updated:

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/simple_gap_decision_review.py --date YYYY-MM-DD
```

The existing full `candle-update` Discord job runs the same review automatically after a successful complete database update and includes the selection-alpha status in its report.

The review uses the captured first positive-volume one-minute opening price. Daily OHLC applies the stop first when both stop and take-profit are inside the same candle, then the take-profit, otherwise the close proxy. A 0.35% round-trip cost is deducted. This is a paper-only decision-quality audit and is not a fill reconstruction.

## Pre-registered strategy review

The latest 50 completed forward decisions trigger a strategy review when any condition fails:

- average selected-minus-rejected return must be positive;
- profit factor must exceed 1.0 after modeled cost;
- maximum drawdown must not exceed 15%;
- at least 50 completed decisions must exist before a pass is possible.

Passing means only “continue under the existing risk limits.” It never authorizes live trading, raises the budget, or promotes news/disclosure signals.
