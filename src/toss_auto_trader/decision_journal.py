from __future__ import annotations

import json
import math
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping


JOURNAL_VERSION = 1
MAX_DAILY_ENTRIES = 1
MAX_DAILY_TURNOVER_RATIO = 1.0
MIN_FORWARD_DECISIONS = 50
MIN_SELECTION_ALPHA = 0.0
MIN_PROFIT_FACTOR = 1.0
MAX_FORWARD_DRAWDOWN = 0.15

ACCOUNTABILITY_DECISIONS = {"selected_for_order", "not_selected_lower_rank"}


def build_pretrade_memo(
    *,
    strategy_name: str,
    trade_date: str,
    symbol: str,
    candidate_rank: int,
    candidate_count: int,
    open_price: float,
    previous_close: float,
    gap_pct: float,
    previous_volume_ratio: float,
    max_position_krw: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict[str, Any]:
    return {
        "version": JOURNAL_VERSION,
        "decision_id": f"{strategy_name}:{trade_date}:{symbol}",
        "written_before_order": True,
        "hypothesis": {
            "name": "low_volume_gap_mean_reversion",
            "statement": (
                "A comparable large opening gap after below-normal prior volume, during the "
                "pre-registered KOSDAQ pullback regime, can mean-revert intraday."
            ),
            "selection_rule": "buy the lowest opening-price eligible candidate after fail-closed checks",
        },
        "evidence_at_decision": {
            "candidate_rank": int(candidate_rank),
            "candidate_count": int(candidate_count),
            "opening_price": float(open_price),
            "previous_close": float(previous_close),
            "gap_pct": float(gap_pct),
            "previous_volume_ratio": float(previous_volume_ratio),
        },
        "bear_case": [
            "the gap can reflect continuing informed selling rather than temporary overreaction",
            "corporate actions or a non-comparable price basis can make the raw gap invalid",
            "warning status, opening liquidity, or quote drift can make the apparent opportunity untradeable",
            "daily OHLC backtests can overstate executable stop/take-profit outcomes",
        ],
        "trade_invalidation": {
            "stop_loss_pct": float(stop_loss_pct),
            "take_profit_pct": float(take_profit_pct),
            "time_exit": "15:20 KST",
            "fail_closed_before_order": [
                "market gate or timestamp mismatch",
                "previous-close basis mismatch",
                "non-comparable raw gap",
                "blocking Toss or Naver warning",
                "buy quote drift above the chase limit",
                "entry audit write failure",
            ],
        },
        "risk_limits": {
            "max_position_krw": float(max_position_krw),
            "max_daily_entries": MAX_DAILY_ENTRIES,
            "max_daily_turnover_ratio": MAX_DAILY_TURNOVER_RATIO,
            "turnover_measure": "gross daily buy notional / max position capital; sells are excluded",
            "same_day_reentry_allowed": False,
        },
        "strategy_falsification": strategy_falsification_policy(),
    }


def strategy_falsification_policy() -> dict[str, float | int | str]:
    return {
        "scope": "latest completed forward decisions; research review only, never an automatic live approval",
        "minimum_decisions": MIN_FORWARD_DECISIONS,
        "minimum_average_selection_alpha": MIN_SELECTION_ALPHA,
        "minimum_profit_factor": MIN_PROFIT_FACTOR,
        "maximum_drawdown": MAX_FORWARD_DRAWDOWN,
    }


def _positive_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    errors = 0
    if not path.exists():
        return rows, errors
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            errors += 1
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            errors += 1
    return rows, errors


def _terminal_decisions(rows: Iterable[Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("trade_date") or "") != trade_date:
            continue
        decision = str(row.get("decision") or "")
        symbol = str(row.get("symbol") or "").strip()
        if symbol and decision in ACCOUNTABILITY_DECISIONS:
            latest[symbol] = dict(row)
    return sorted(latest.values(), key=lambda row: (int(row.get("candidate_rank") or 10**9), str(row.get("symbol"))))


def _daily_candles(db_path: Path | str, trade_date: str, symbols: list[str]) -> dict[str, dict[str, float]]:
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    sql = f"""
        SELECT symbol, open_price, high_price, low_price, close_price
        FROM candle_cache
        WHERE interval='1d' AND substr(timestamp,1,10)=? AND symbol IN ({placeholders})
    """
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        raw = connection.execute(sql, [trade_date, *symbols]).fetchall()
    finally:
        connection.close()
    candles: dict[str, dict[str, float]] = {}
    for symbol, open_price, high_price, low_price, close_price in raw:
        values = [_positive_float(value) for value in (open_price, high_price, low_price, close_price)]
        if all(value is not None for value in values):
            candles[str(symbol)] = dict(zip(("open", "high", "low", "close"), values, strict=True))
    return candles


def counterfactual_return(
    *,
    entry_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    roundtrip_cost: float,
) -> tuple[float, str, float]:
    stop = entry_price * (1.0 - stop_loss_pct)
    take = entry_price * (1.0 + take_profit_pct)
    if low_price <= stop:
        exit_price = stop
        exit_reason = "stop_first_daily_ohlc"
    elif high_price >= take:
        exit_price = take
        exit_reason = "take_profit"
    else:
        exit_price = close_price
        exit_reason = "close_proxy"
    return exit_price / entry_price - 1.0 - roundtrip_cost, exit_reason, exit_price


def review_trade_date(
    db_path: Path | str,
    audit_path: Path,
    trade_date: str,
    *,
    stop_loss_pct: float = 0.0225,
    take_profit_pct: float = 0.12,
    roundtrip_cost: float = 0.0035,
) -> dict[str, Any]:
    rows, parse_errors = _read_jsonl(audit_path)
    decisions = _terminal_decisions(rows, trade_date)
    if not audit_path.exists():
        return {"status": "missing_audit_file", "trade_date": trade_date, "audit_parse_errors": 0, "outcomes": []}
    if parse_errors:
        return {"status": "audit_parse_error", "trade_date": trade_date, "audit_parse_errors": parse_errors, "outcomes": []}
    if not decisions:
        return {"status": "no_accountability_decisions", "trade_date": trade_date, "audit_parse_errors": 0, "outcomes": []}
    symbols = [str(row["symbol"]) for row in decisions]
    candles = _daily_candles(db_path, trade_date, symbols)
    outcomes: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    for row in decisions:
        symbol = str(row["symbol"])
        candle = candles.get(symbol)
        entry = _positive_float(row.get("first_minute_open"))
        if candle is None or entry is None:
            missing_symbols.append(symbol)
            continue
        net_return, exit_reason, exit_price = counterfactual_return(
            entry_price=entry,
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            roundtrip_cost=roundtrip_cost,
        )
        outcomes.append(
            {
                "symbol": symbol,
                "candidate_rank": int(row.get("candidate_rank") or 0),
                "decision": row.get("decision"),
                "decision_id": (row.get("pretrade_memo") or {}).get("decision_id"),
                "execution_checks_complete": row.get("execution_checks_complete"),
                "counterfactual_scope": row.get("counterfactual_scope"),
                "entry_price": entry,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "net_return": net_return,
            }
        )
    selected = next((row for row in outcomes if row["decision"] == "selected_for_order"), None)
    rejected = [row for row in outcomes if row["decision"] == "not_selected_lower_rank"]
    rejected_mean = statistics.mean(float(row["net_return"]) for row in rejected) if rejected else None
    selection_alpha = None
    if selected is not None and rejected_mean is not None:
        selection_alpha = float(selected["net_return"]) - rejected_mean
    return {
        "status": "missing_official_candles" if missing_symbols else "ok",
        "trade_date": trade_date,
        "audit_parse_errors": 0,
        "selected_symbol": None if selected is None else selected["symbol"],
        "selected_net_return": None if selected is None else selected["net_return"],
        "rejected_candidates": len(rejected),
        "rejected_mean_net_return": rejected_mean,
        "selection_alpha": selection_alpha,
        "selected_beats_rejected_mean": None if selection_alpha is None else selection_alpha > 0,
        "missing_symbols": missing_symbols,
        "outcomes": outcomes,
        "assumptions": {
            "entry": "first positive-volume 1-minute opening price captured before order",
            "exit": "daily OHLC stop-first, then take-profit, otherwise close proxy",
            "roundtrip_cost": roundtrip_cost,
            "order_sent": False,
            "rejected_scope": "screening quality only; lower ranks were not re-quoted or warning-checked after selection",
        },
    }


def _max_drawdown(returns: Iterable[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def evaluate_strategy_metrics(
    *,
    decisions: int,
    average_selection_alpha: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
) -> dict[str, Any]:
    checks = {
        "minimum_decisions": decisions >= MIN_FORWARD_DECISIONS,
        "positive_selection_alpha": average_selection_alpha is not None and average_selection_alpha > MIN_SELECTION_ALPHA,
        "profit_factor": profit_factor is not None and profit_factor > MIN_PROFIT_FACTOR,
        "max_drawdown": max_drawdown is not None and max_drawdown <= MAX_FORWARD_DRAWDOWN,
    }
    if not checks["minimum_decisions"]:
        status = "insufficient_forward_sample"
    elif all(checks.values()):
        status = "continue_under_existing_risk_limits"
    else:
        status = "strategy_review_required"
    return {"status": status, "checks": checks, "policy": strategy_falsification_policy()}


def rolling_strategy_review(review_log_path: Path, *, limit: int = MIN_FORWARD_DECISIONS) -> dict[str, Any]:
    rows, parse_errors = _read_jsonl(review_log_path)
    latest_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        if trade_date and row.get("status") == "ok" and row.get("selected_net_return") is not None:
            latest_by_date[trade_date] = row
    usable = [latest_by_date[date] for date in sorted(latest_by_date)][-limit:]
    returns = [float(row["selected_net_return"]) for row in usable]
    alphas = [float(row["selection_alpha"]) for row in usable if row.get("selection_alpha") is not None]
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    profit_factor = math.inf if losses <= 0 and gains > 0 else (None if losses <= 0 else gains / losses)
    result = evaluate_strategy_metrics(
        decisions=len(usable),
        average_selection_alpha=statistics.mean(alphas) if alphas else None,
        profit_factor=profit_factor,
        max_drawdown=_max_drawdown(returns) if returns else None,
    )
    return {
        **result,
        "reviewed_decisions": len(usable),
        "paired_alpha_decisions": len(alphas),
        "average_selection_alpha": statistics.mean(alphas) if alphas else None,
        "profit_factor": profit_factor,
        "max_drawdown": _max_drawdown(returns) if returns else None,
        "parse_errors": parse_errors,
        "live_order_allowed": False,
    }
