from __future__ import annotations

import json
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader import decision_journal


def load_trader():
    path = Path(__file__).resolve().parents[1] / "scripts" / "simple_gap_trader.py"
    spec = importlib.util.spec_from_file_location("decision_journal_test_trader", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DecisionJournalTests(unittest.TestCase):
    def test_pretrade_memo_is_falsifiable_and_has_explicit_turnover_limit(self):
        memo = decision_journal.build_pretrade_memo(
            strategy_name="test",
            trade_date="2026-08-10",
            symbol="123456",
            candidate_rank=1,
            candidate_count=3,
            open_price=1000,
            previous_close=1100,
            gap_pct=-9.09,
            previous_volume_ratio=0.5,
            max_position_krw=10_000,
            stop_loss_pct=0.0225,
            take_profit_pct=0.12,
        )

        self.assertTrue(memo["written_before_order"])
        self.assertTrue(memo["bear_case"])
        self.assertEqual(memo["risk_limits"]["max_daily_entries"], 1)
        self.assertEqual(memo["risk_limits"]["max_daily_turnover_ratio"], 1.0)
        self.assertIn("gross daily buy notional", memo["risk_limits"]["turnover_measure"])
        self.assertEqual(memo["strategy_falsification"]["minimum_decisions"], 50)

    def test_post_close_review_compares_selected_and_rejected_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "candles.sqlite3"
            audit_path = root / "audit.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL)"
            )
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?)",
                [
                    ("SELECTED", "1d", "2026-08-10T00:00:00+09:00", 1000, 1010, 990, 1010),
                    ("REJECTED", "1d", "2026-08-10T00:00:00+09:00", 2000, 2200, 1990, 2180),
                ],
            )
            connection.commit()
            connection.close()
            audit_path.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "trade_date": "2026-08-10", "symbol": "SELECTED", "candidate_rank": 1,
                            "decision": "selected_for_order", "first_minute_open": 1000,
                            "pretrade_memo": {"decision_id": "d1"},
                        }),
                        json.dumps({
                            "trade_date": "2026-08-10", "symbol": "REJECTED", "candidate_rank": 2,
                            "decision": "not_selected_lower_rank", "first_minute_open": 2000,
                            "pretrade_memo": {"decision_id": "d2"},
                        }),
                    ]
                ) + "\n",
                encoding="utf-8",
            )

            result = decision_journal.review_trade_date(db_path, audit_path, "2026-08-10")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["selected_symbol"], "SELECTED")
        self.assertEqual(result["rejected_candidates"], 1)
        self.assertLess(result["selection_alpha"], 0)
        self.assertFalse(result["selected_beats_rejected_mean"])

    def test_daily_ohlc_uses_stop_first_when_stop_and_take_both_hit(self):
        net_return, reason, exit_price = decision_journal.counterfactual_return(
            entry_price=1000,
            high_price=1200,
            low_price=900,
            close_price=1100,
            stop_loss_pct=0.0225,
            take_profit_pct=0.12,
            roundtrip_cost=0.0035,
        )

        self.assertEqual(reason, "stop_first_daily_ohlc")
        self.assertAlmostEqual(exit_price, 977.5)
        self.assertAlmostEqual(net_return, -0.026)

    def test_strategy_review_requires_forward_sample_and_all_risk_checks(self):
        insufficient = decision_journal.evaluate_strategy_metrics(
            decisions=49,
            average_selection_alpha=0.01,
            profit_factor=2.0,
            max_drawdown=0.05,
        )
        failed = decision_journal.evaluate_strategy_metrics(
            decisions=50,
            average_selection_alpha=-0.001,
            profit_factor=2.0,
            max_drawdown=0.05,
        )
        passed = decision_journal.evaluate_strategy_metrics(
            decisions=50,
            average_selection_alpha=0.001,
            profit_factor=1.1,
            max_drawdown=0.149,
        )

        self.assertEqual(insufficient["status"], "insufficient_forward_sample")
        self.assertEqual(failed["status"], "strategy_review_required")
        self.assertEqual(passed["status"], "continue_under_existing_risk_limits")

    def test_corrupt_audit_fails_closed_instead_of_partial_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_path = root / "audit.jsonl"
            audit_path.write_text("not-json\n", encoding="utf-8")

            result = decision_journal.review_trade_date(root / "missing.sqlite3", audit_path, "2026-08-10")

        self.assertEqual(result["status"], "audit_parse_error")
        self.assertEqual(result["audit_parse_errors"], 1)

    def test_live_helper_records_every_lower_rank_without_sending_orders(self):
        trader = load_trader()
        rows = []
        selected = {
            "symbol": "A", "candidate_rank": 1, "open_price": 1000, "prev_close": 1100,
            "gap_pct": -9.09, "prev_vol_ratio": 0.5,
        }
        rejected = {
            "symbol": "B", "candidate_rank": 2, "open_price": 2000, "prev_close": 2200,
            "gap_pct": -9.09, "prev_vol_ratio": 0.4,
        }
        original = trader.append_entry_price_audit
        trader.append_entry_price_audit = rows.append
        try:
            trader.record_unselected_lower_rank_candidates(
                [selected, rejected],
                selected_target=selected,
                trade_date="2026-08-10",
            )
        finally:
            trader.append_entry_price_audit = original

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "B")
        self.assertEqual(rows[0]["decision"], "not_selected_lower_rank")
        self.assertFalse(rows[0]["order_sent"])
        self.assertFalse(rows[0]["execution_checks_complete"])
        self.assertEqual(rows[0]["counterfactual_scope"], "screening_quality_not_executable_fill")
        self.assertTrue(rows[0]["pretrade_memo"]["written_before_order"])

    def test_rolling_review_deduplicates_repeated_daily_candle_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.jsonl"
            rows = []
            for day in range(1, 51):
                payload = {
                    "status": "ok",
                    "trade_date": f"2026-06-{day:02d}",
                    "selected_net_return": 0.01,
                    "selection_alpha": 0.001,
                }
                rows.append(json.dumps(payload))
                if day == 50:
                    rows.append(json.dumps(payload))
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")

            review = decision_journal.rolling_strategy_review(path)

        self.assertEqual(review["reviewed_decisions"], 50)
        self.assertEqual(review["status"], "continue_under_existing_risk_limits")
