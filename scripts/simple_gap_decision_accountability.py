#!/usr/bin/env python3
"""Audit selected and rejected simple-gap candidates with identical assumptions.

This is a read-only, order-free research tool.  It answers the accountability
question that a top-1 strategy normally hides: did the chosen name outperform
the other eligible names that were intentionally not traded?
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from kosdaq_sma5_gate_deep_dive import GateRow, gate_rows, to_index_candles
from simple_gap_strategy_audit import fetch_kosdaq_index
from simple_gap_variant_core import (
    Candidate,
    TradeResult,
    VariantConfig,
    compounded,
    max_drawdown,
    passes_filters,
    rank_value,
    simulate_day,
)
from simple_gap_variant_data import load_candidates
from toss_auto_trader import decision_journal

MIN_COMPARABLE_GAP = -0.31


@dataclass(frozen=True, slots=True)
class DecisionDay:
    date: str
    eligible_candidates: int
    selected_symbol: str
    selected_return: float
    rejected_mean_return: float | None
    rejected_best_return: float | None
    selected_rank_by_outcome: int
    selection_alpha: float | None
    oracle_regret: float


def live_config() -> VariantConfig:
    return VariantConfig(
        "robust_gap5_stop0225_take12",
        10_000.0,
        1_000.0,
        8_000.0,
        -0.05,
        0.0,
        0.8,
        0,
        1,
        "lowest_price",
        0.0035,
        0.0,
        0.0225,
        0.12,
    )


def fetch_kosdaq_index_chunked(start: str, end: str) -> list[dict[str, object]]:
    """Avoid one fragile decade-long chunked HTTP response from the index API."""
    start_year = int(start[:4])
    end_year = int(end[:4])
    rows_by_date: dict[str, dict[str, object]] = {}
    for year in range(start_year, end_year + 1):
        chunk_start = max(start, f"{year}-01-01")
        chunk_end = min(end, f"{year}-12-31")
        for row in fetch_kosdaq_index(chunk_start, chunk_end):
            rows_by_date[str(row["date"])] = dict(row)
    return [rows_by_date[date] for date in sorted(rows_by_date)]


def trade_for_candidate(candidate: Candidate, config: VariantConfig) -> TradeResult | None:
    _day_return, trades = simulate_day([candidate], config)
    return trades[0] if trades else None


def eligible_by_date(rows: Sequence[Candidate], config: VariantConfig) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        if MIN_COMPARABLE_GAP <= row.gap_return and passes_filters(row, config) and row.open_price <= config.capital:
            grouped[row.date].append(row)
    return dict(grouped)


def decision_days(rows: Sequence[Candidate], config: VariantConfig) -> tuple[list[DecisionDay], list[TradeResult], list[TradeResult]]:
    decisions: list[DecisionDay] = []
    selected_trades: list[TradeResult] = []
    rejected_trades: list[TradeResult] = []
    for date, candidates in sorted(eligible_by_date(rows, config).items()):
        ranked = sorted(candidates, key=lambda row: rank_value(row, config.rank))
        outcomes = [(candidate, trade_for_candidate(candidate, config)) for candidate in ranked]
        outcomes = [(candidate, trade) for candidate, trade in outcomes if trade is not None]
        if not outcomes:
            continue
        selected_candidate, selected = outcomes[0]
        rejected = [trade for _candidate, trade in outcomes[1:]]
        selected_trades.append(selected)
        rejected_trades.extend(rejected)
        all_returns = [trade.net_return for _candidate, trade in outcomes]
        rejected_returns = [trade.net_return for trade in rejected]
        rejected_mean = statistics.mean(rejected_returns) if rejected_returns else None
        rejected_best = max(rejected_returns) if rejected_returns else None
        decisions.append(
            DecisionDay(
                date=date,
                eligible_candidates=len(outcomes),
                selected_symbol=selected_candidate.symbol,
                selected_return=selected.net_return,
                rejected_mean_return=rejected_mean,
                rejected_best_return=rejected_best,
                selected_rank_by_outcome=1 + sum(value > selected.net_return for value in all_returns),
                selection_alpha=None if rejected_mean is None else selected.net_return - rejected_mean,
                oracle_regret=max(all_returns) - selected.net_return,
            )
        )
    return decisions, selected_trades, rejected_trades


def trade_summary(trades: Sequence[TradeResult]) -> dict[str, float | int | None]:
    if not trades:
        return {
            "trades": 0,
            "win_rate": None,
            "avg_return": None,
            "median_return": None,
            "total_pnl": 0.0,
            "profit_factor": None,
        }
    returns = [trade.net_return for trade in trades]
    gains = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0)
    losses = -sum(trade.net_pnl for trade in trades if trade.net_pnl < 0)
    return {
        "trades": len(trades),
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "avg_return": statistics.mean(returns),
        "median_return": statistics.median(returns),
        "total_pnl": sum(trade.net_pnl for trade in trades),
        "profit_factor": None if losses <= 0 else gains / losses,
    }


def fixed_capital_metrics(trades: Sequence[TradeResult], *, capital: float) -> dict[str, float]:
    equity = capital
    peak = capital
    worst = 0.0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return {
        "account_return": (equity - capital) / capital,
        "max_drawdown": worst,
    }


def market_benchmark(decisions: Sequence[DecisionDay], gates: Mapping[str, GateRow]) -> dict[str, float | int | None]:
    active_dates = [row.date for row in decisions if row.date in gates]
    active_returns = [gates[date].close_price / gates[date].open_price - 1.0 for date in active_dates]
    if not active_returns:
        return {"active_days": 0, "compounded_open_to_close": None, "max_drawdown": None, "full_period_return": None}
    first = gates[active_dates[0]]
    last = gates[active_dates[-1]]
    return {
        "active_days": len(active_returns),
        "compounded_open_to_close": compounded(active_returns),
        "max_drawdown": max_drawdown(active_returns),
        "full_period_return": last.close_price / first.open_price - 1.0,
    }


def selection_summary(
    decisions: Sequence[DecisionDay],
    selected: Sequence[TradeResult],
    rejected: Sequence[TradeResult],
    *,
    capital: float,
) -> dict[str, object]:
    paired = [row for row in decisions if row.selection_alpha is not None]
    fixed = fixed_capital_metrics(selected, capital=capital)
    return {
        "decision_days": len(decisions),
        "days_with_alternatives": len(paired),
        "eligible_candidate_observations": sum(row.eligible_candidates for row in decisions),
        "selected": trade_summary(selected),
        "rejected_counterfactuals": trade_summary(rejected),
        "selected_fixed_capital_return": fixed["account_return"],
        "selected_fixed_capital_max_drawdown": fixed["max_drawdown"],
        "selected_beats_rejected_mean_rate": (
            None if not paired else sum(float(row.selection_alpha) > 0 for row in paired) / len(paired)
        ),
        "selected_was_best_rate": (
            None if not paired else sum(row.selected_rank_by_outcome == 1 for row in paired) / len(paired)
        ),
        "avg_selection_alpha": (
            None if not paired else statistics.mean(float(row.selection_alpha) for row in paired)
        ),
        "avg_oracle_regret": (
            None if not decisions else statistics.mean(row.oracle_regret for row in decisions)
        ),
        "selected_losses": sum(trade.net_return <= 0 for trade in selected),
        "rejected_winners": sum(trade.net_return > 0 for trade in rejected),
        "selected_loss_with_positive_rejected_best_days": sum(
            row.selected_return <= 0 and (row.rejected_best_return or 0.0) > 0 for row in paired
        ),
        "worst_selection_alpha_days": [
            asdict(row)
            for row in sorted(paired, key=lambda item: float(item.selection_alpha))[:10]
        ],
        "best_selection_alpha_days": [
            asdict(row)
            for row in sorted(paired, key=lambda item: float(item.selection_alpha), reverse=True)[:10]
        ],
    }


def rank_comparison(rows: Sequence[Candidate], config: VariantConfig) -> dict[str, dict[str, float | int | None]]:
    comparison: dict[str, dict[str, float | int | None]] = {}
    for rank in ["lowest_price", "largest_gap", "quiet_volume", "highest_price", "gap_then_quiet"]:
        ranked_config = replace(config, name=f"{config.name}_{rank}", rank=rank)
        _decisions, selected, _rejected = decision_days(rows, ranked_config)
        fixed = fixed_capital_metrics(selected, capital=config.capital)
        comparison[rank] = {
            **trade_summary(selected),
            "fixed_capital_return": fixed["account_return"],
            "fixed_capital_max_drawdown": fixed["max_drawdown"],
        }
    return comparison


def analyze(
    rows: Sequence[Candidate],
    gates: Mapping[str, GateRow],
    config: VariantConfig,
    *,
    start: str,
    end: str,
) -> dict[str, object]:
    scoped = [row for row in rows if start <= row.date <= end and row.date in gates]
    decisions, selected, rejected = decision_days(scoped, config)
    selection = selection_summary(decisions, selected, rejected, capital=config.capital)
    selected_summary = selection["selected"]
    assert isinstance(selected_summary, Mapping)
    return {
        "start": start,
        "end": end,
        "candidate_rows": len(scoped),
        "selection": selection,
        "rank_comparison": rank_comparison(scoped, config),
        "kosdaq_benchmark": market_benchmark(decisions, gates),
        "strategy_review": decision_journal.evaluate_strategy_metrics(
            decisions=int(selection["decision_days"]),
            average_selection_alpha=selection["avg_selection_alpha"],
            profit_factor=selected_summary["profit_factor"],
            max_drawdown=selection["selected_fixed_capital_max_drawdown"],
        ),
    }


def pct(value: object) -> str:
    return "n/a" if value is None else f"{float(value) * 100:+.2f}%"


def markdown(payload: Mapping[str, object]) -> str:
    lines = [
        "# Simple Gap Decision Accountability Audit",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        "- order_sent: `false`",
        "- live_order_allowed: `false`",
        "- principle: compare the selected candidate and every rejected eligible candidate under identical exit and cost assumptions.",
        "- counter-thesis: a profitable strategy can still use a weak ranking rule; selection alpha must be measured separately from total strategy return.",
        "",
    ]
    windows = payload["windows"]
    assert isinstance(windows, Mapping)
    for name, item in windows.items():
        assert isinstance(item, Mapping)
        selection = item["selection"]
        benchmark = item["kosdaq_benchmark"]
        ranks = item["rank_comparison"]
        review = item["strategy_review"]
        assert isinstance(selection, Mapping) and isinstance(benchmark, Mapping) and isinstance(ranks, Mapping) and isinstance(review, Mapping)
        selected = selection["selected"]
        rejected = selection["rejected_counterfactuals"]
        assert isinstance(selected, Mapping) and isinstance(rejected, Mapping)
        lines += [
            f"## {name}: {item['start']}~{item['end']}",
            "",
            f"- decisions: {selection['decision_days']} days / alternatives available: {selection['days_with_alternatives']} days",
            f"- selected: {selected['trades']} trades / fixed-capital return {pct(selection['selected_fixed_capital_return'])} / cash MDD {pct(selection['selected_fixed_capital_max_drawdown'])} / win {pct(selected['win_rate'])}",
            f"- rejected counterfactuals: {rejected['trades']} observations / avg {pct(rejected['avg_return'])} / win {pct(rejected['win_rate'])}",
            f"- selection alpha vs rejected mean: {pct(selection['avg_selection_alpha'])} / beat rate {pct(selection['selected_beats_rejected_mean_rate'])}",
            f"- selected was hindsight-best: {pct(selection['selected_was_best_rate'])} / average oracle regret {pct(selection['avg_oracle_regret'])}",
            f"- selected losses: {selection['selected_losses']} / rejected winners disclosed: {selection['rejected_winners']}",
            f"- pre-registered strategy review: `{review['status']}`",
            f"- KOSDAQ first-to-last active-date buy-and-hold: {pct(benchmark['full_period_return'])}",
            f"- KOSDAQ strategy-active-day open-to-close path: {pct(benchmark['compounded_open_to_close'])} / MDD {pct(benchmark['max_drawdown'])}",
            "",
            "| rank rule | trades | fixed-capital return | cash MDD | win | total PnL |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for rank, metrics in ranks.items():
            assert isinstance(metrics, Mapping)
            lines.append(
                f"| {rank} | {metrics['trades']} | {pct(metrics['fixed_capital_return'])} | "
                f"{pct(metrics['fixed_capital_max_drawdown'])} | {pct(metrics['win_rate'])} | {float(metrics['total_pnl']):,.0f} KRW |"
            )
        lines.append("")
    lines += [
        "## Interpretation boundary",
        "",
        "Daily OHLC cannot determine whether the stop or take-profit was hit first when both occur in one candle. The shared simulator conservatively applies the stop first. Rejected outcomes are counterfactual, not executable fills, and this audit does not promote news, disclosure, or any ranking rule into live trading.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, object]:
    config = live_config()
    rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=config.gap_threshold)
    index_rows = to_index_candles(fetch_kosdaq_index_chunked(args.start, args.end))
    gates_all = gate_rows(index_rows)
    eligible_dates = {date for date, row in gates_all.items() if row.open_vs_live_sma5 <= -0.01}
    gates = {date: row for date, row in gates_all.items() if date in eligible_dates}
    windows = {
        "full": (args.start, args.end),
        "train_2016_2023": (args.start, min(args.end, "2023-12-31")),
        "test_2024_2026": (max(args.start, "2024-01-01"), args.end),
        "recent_2025_2026": (max(args.start, "2025-01-01"), args.end),
    }
    payload: dict[str, object] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "paper_only_decision_accountability_backtest",
        "order_sent": False,
        "live_order_allowed": False,
        "source_db": args.db_path,
        "strategy": asdict(config),
        "market_gate": "KOSDAQ open <= live-style SMA5 * 0.99",
        "gap_integrity_range": {"minimum": MIN_COMPARABLE_GAP, "maximum": config.gap_threshold},
        "index_rows": len(index_rows),
        "windows": {
            name: analyze(rows, gates, config, start=start, end=end)
            for name, (start, end) in windows.items()
            if start <= end
        },
    }
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare selected and rejected simple-gap candidates")
    parser.add_argument("--db-path", default="data/edge_research_universe_15y.sqlite3")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--out-json", default="data/decision_accountability/latest.json")
    parser.add_argument("--out-md", default="docs/SIMPLE_GAP_DECISION_ACCOUNTABILITY_LATEST.md")
    args = parser.parse_args()
    payload = run(args)
    windows = payload["windows"]
    assert isinstance(windows, Mapping)
    full = windows["full"]
    assert isinstance(full, Mapping)
    selection = full["selection"]
    assert isinstance(selection, Mapping)
    print(json.dumps({
        "out_json": args.out_json,
        "out_md": args.out_md,
        "decision_days": selection["decision_days"],
        "selected_fixed_capital_return": selection["selected_fixed_capital_return"],
        "avg_selection_alpha": selection["avg_selection_alpha"],
        "order_sent": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
