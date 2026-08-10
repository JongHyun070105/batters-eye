from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module():
    path = SCRIPTS / "simple_gap_decision_accountability.py"
    spec = importlib.util.spec_from_file_location("simple_gap_decision_accountability", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DecisionAccountabilityTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.core = sys.modules["simple_gap_variant_core"]

    def candidate(self, symbol: str, open_price: float, close_price: float, *, gap_return: float = -0.10):
        return self.core.Candidate(
            date="2026-01-02",
            symbol=symbol,
            prev_close=open_price / 0.90,
            open_price=open_price,
            close_price=close_price,
            high_price=max(open_price, close_price),
            low_price=min(open_price, close_price),
            gap_return=gap_return,
            prev_vol_ratio=0.5,
            future_closes=(),
        )

    def test_discloses_rejected_winner_when_lowest_price_loses(self):
        config = self.mod.live_config()
        rows = [
            self.candidate("LOW", 1_000, 970),
            self.candidate("HIGH", 2_000, 2_100),
        ]
        decisions, selected, rejected = self.mod.decision_days(rows, config)
        summary = self.mod.selection_summary(decisions, selected, rejected, capital=config.capital)

        self.assertEqual(selected[0].symbol, "LOW")
        self.assertEqual(rejected[0].symbol, "HIGH")
        self.assertEqual(summary["selected_losses"], 1)
        self.assertEqual(summary["rejected_winners"], 1)
        self.assertEqual(summary["selected_loss_with_positive_rejected_best_days"], 1)
        self.assertLess(summary["avg_selection_alpha"], 0)

    def test_selected_best_rate_uses_paired_days_only(self):
        config = self.mod.live_config()
        rows = [
            self.candidate("LOW", 1_000, 1_100),
            self.candidate("HIGH", 2_000, 2_020),
        ]
        decisions, selected, rejected = self.mod.decision_days(rows, config)
        summary = self.mod.selection_summary(decisions, selected, rejected, capital=config.capital)

        self.assertEqual(summary["days_with_alternatives"], 1)
        self.assertEqual(summary["selected_was_best_rate"], 1.0)
        self.assertEqual(summary["selected_beats_rejected_mean_rate"], 1.0)
        self.assertGreater(summary["avg_selection_alpha"], 0)

    def test_unaffordable_candidate_is_not_a_counterfactual(self):
        config = self.mod.live_config()
        rows = [
            self.candidate("LOW", 1_000, 1_010),
            self.candidate("TOO_EXPENSIVE", 12_000, 13_000),
        ]
        decisions, selected, rejected = self.mod.decision_days(rows, config)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].eligible_candidates, 1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(rejected, [])

    def test_fixed_capital_return_does_not_assume_reinvestment(self):
        config = self.mod.live_config()
        trades = [
            self.mod.TradeResult("2026-01-01", "A", 1_000, 1_100, 10, 10_000, 1_000, 0.10, -0.10, 0.5),
            self.mod.TradeResult("2026-01-02", "B", 1_000, 1_100, 10, 10_000, 1_000, 0.10, -0.10, 0.5),
        ]

        metrics = self.mod.fixed_capital_metrics(trades, capital=config.capital)

        self.assertAlmostEqual(metrics["account_return"], 0.20)

    def test_noncomparable_gap_below_live_integrity_floor_is_excluded(self):
        config = self.mod.live_config()
        rows = [
            self.candidate("VALID", 1_000, 1_010),
            self.candidate("NONCOMPARABLE", 1_000, 1_120, gap_return=-0.40),
        ]

        decisions, selected, rejected = self.mod.decision_days(rows, config)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(selected[0].symbol, "VALID")
        self.assertEqual(rejected, [])

    def test_index_fetch_is_split_by_calendar_year(self):
        calls = []

        def fake_fetch(start, end):
            calls.append((start, end))
            return [{"date": start, "open": 100, "close": 101}]

        with patch.object(self.mod, "fetch_kosdaq_index", side_effect=fake_fetch):
            rows = self.mod.fetch_kosdaq_index_chunked("2024-06-01", "2026-02-01")

        self.assertEqual(
            calls,
            [
                ("2024-06-01", "2024-12-31"),
                ("2025-01-01", "2025-12-31"),
                ("2026-01-01", "2026-02-01"),
            ],
        )
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
