#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from toss_auto_trader import decision_journal, simple_gap_state


DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_AUDIT_LOG = Path("logs/simple_gap_entry_price_audit.jsonl")
DEFAULT_REVIEW_LOG = Path("logs/simple_gap_decision_review.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review selected and rejected live candidates after the close")
    parser.add_argument("--date", default=datetime.now().astimezone().date().isoformat())
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_LOG))
    parser.add_argument("--review-log", default=str(DEFAULT_REVIEW_LOG))
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    result = decision_journal.review_trade_date(
        args.db_path,
        Path(args.audit_log),
        args.date,
    )
    result["recorded_at"] = datetime.now().astimezone().isoformat()
    if not args.print_only:
        simple_gap_state.append_event(Path(args.review_log), result)
    result["rolling_strategy_review"] = decision_journal.rolling_strategy_review(Path(args.review_log))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"ok", "no_accountability_decisions"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
