# Simple Gap Decision Accountability Audit

- generated_at: `2026-08-10T20:02:33.656877+09:00`
- order_sent: `false`
- live_order_allowed: `false`
- principle: compare the selected candidate and every rejected eligible candidate under identical exit and cost assumptions.
- counter-thesis: a profitable strategy can still use a weak ranking rule; selection alpha must be measured separately from total strategy return.

## full: 2016-01-01~2026-08-10

- decisions: 293 days / alternatives available: 217 days
- selected: 293 trades / fixed-capital return +1022.27% / cash MDD +2.09% / win +62.80%
- rejected counterfactuals: 4070 observations / avg +1.40% / win +50.88%
- selection alpha vs rejected mean: +1.32% / beat rate +56.68%
- selected was hindsight-best: +32.26% / average oracle regret +3.00%
- selected losses: 109 / rejected winners disclosed: 2071
- pre-registered strategy review: `continue_under_existing_risk_limits`
- KOSDAQ first-to-last active-date buy-and-hold: +8.12%
- KOSDAQ strategy-active-day open-to-close path: -67.64% / MDD +72.59%

| rank rule | trades | fixed-capital return | cash MDD | win | total PnL |
|---|---:|---:|---:|---:|---:|
| lowest_price | 293 | +1022.27% | +2.09% | +62.80% | 102,227 KRW |
| largest_gap | 293 | +1017.04% | +3.02% | +58.02% | 101,704 KRW |
| quiet_volume | 293 | +866.74% | +3.25% | +57.00% | 86,674 KRW |
| highest_price | 293 | +602.48% | +3.71% | +53.58% | 60,248 KRW |
| gap_then_quiet | 293 | +1017.04% | +3.02% | +58.02% | 101,704 KRW |

## train_2016_2023: 2016-01-01~2023-12-31

- decisions: 211 days / alternatives available: 152 days
- selected: 211 trades / fixed-capital return +740.79% / cash MDD +2.09% / win +61.61%
- rejected counterfactuals: 3032 observations / avg +1.33% / win +50.92%
- selection alpha vs rejected mean: +1.03% / beat rate +57.24%
- selected was hindsight-best: +31.58% / average oracle regret +2.93%
- selected losses: 81 / rejected winners disclosed: 1544
- pre-registered strategy review: `continue_under_existing_risk_limits`
- KOSDAQ first-to-last active-date buy-and-hold: +16.33%
- KOSDAQ strategy-active-day open-to-close path: -42.90% / MDD +49.26%

| rank rule | trades | fixed-capital return | cash MDD | win | total PnL |
|---|---:|---:|---:|---:|---:|
| lowest_price | 211 | +740.79% | +2.09% | +61.61% | 74,079 KRW |
| largest_gap | 211 | +838.43% | +3.02% | +60.19% | 83,843 KRW |
| quiet_volume | 211 | +725.28% | +3.25% | +60.66% | 72,528 KRW |
| highest_price | 211 | +498.01% | +3.71% | +54.03% | 49,801 KRW |
| gap_then_quiet | 211 | +838.43% | +3.02% | +60.19% | 83,843 KRW |

## test_2024_2026: 2024-01-01~2026-08-10

- decisions: 82 days / alternatives available: 65 days
- selected: 82 trades / fixed-capital return +281.47% / cash MDD +3.47% / win +65.85%
- rejected counterfactuals: 1038 observations / avg +1.62% / win +50.77%
- selection alpha vs rejected mean: +2.01% / beat rate +55.38%
- selected was hindsight-best: +33.85% / average oracle regret +3.18%
- selected losses: 28 / rejected winners disclosed: 527
- pre-registered strategy review: `continue_under_existing_risk_limits`
- KOSDAQ first-to-last active-date buy-and-hold: -13.70%
- KOSDAQ strategy-active-day open-to-close path: -43.33% / MDD +49.18%

| rank rule | trades | fixed-capital return | cash MDD | win | total PnL |
|---|---:|---:|---:|---:|---:|
| lowest_price | 82 | +281.47% | +3.47% | +65.85% | 28,147 KRW |
| largest_gap | 82 | +178.60% | +9.44% | +52.44% | 17,860 KRW |
| quiet_volume | 82 | +141.47% | +8.01% | +47.56% | 14,147 KRW |
| highest_price | 82 | +104.47% | +6.65% | +52.44% | 10,447 KRW |
| gap_then_quiet | 82 | +178.60% | +9.44% | +52.44% | 17,860 KRW |

## recent_2025_2026: 2025-01-01~2026-08-10

- decisions: 59 days / alternatives available: 52 days
- selected: 59 trades / fixed-capital return +238.32% / cash MDD +3.42% / win +71.19%
- rejected counterfactuals: 890 observations / avg +1.60% / win +50.22%
- selection alpha vs rejected mean: +2.52% / beat rate +59.62%
- selected was hindsight-best: +36.54% / average oracle regret +3.10%
- selected losses: 17 / rejected winners disclosed: 447
- pre-registered strategy review: `continue_under_existing_risk_limits`
- KOSDAQ first-to-last active-date buy-and-hold: +0.21%
- KOSDAQ strategy-active-day open-to-close path: -40.66% / MDD +45.05%

| rank rule | trades | fixed-capital return | cash MDD | win | total PnL |
|---|---:|---:|---:|---:|---:|
| lowest_price | 59 | +238.32% | +3.42% | +71.19% | 23,832 KRW |
| largest_gap | 59 | +158.65% | +7.70% | +55.93% | 15,865 KRW |
| quiet_volume | 59 | +107.56% | +9.81% | +47.46% | 10,756 KRW |
| highest_price | 59 | +73.85% | +7.82% | +52.54% | 7,385 KRW |
| gap_then_quiet | 59 | +158.65% | +7.70% | +55.93% | 15,865 KRW |

## Interpretation boundary

Daily OHLC cannot determine whether the stop or take-profit was hit first when both occur in one candle. The shared simulator conservatively applies the stop first. Rejected outcomes are counterfactual, not executable fills, and this audit does not promote news, disclosure, or any ranking rule into live trading.
