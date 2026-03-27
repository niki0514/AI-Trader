from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters import read_json, write_json
from app.config import load_pipeline_config
from app.pipeline.context import RunContext
from app.runner import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI Trader backend v2 for a single day snapshot.")
    parser.add_argument("--input", default=str(BACKEND_DIR / "examples" / "input" / "daily_snapshot.json"))
    parser.add_argument("--config", default=str(BACKEND_DIR / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--output-root", default=str(BACKEND_DIR / "outputs"))
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--pipeline-preset", default="")
    parser.add_argument("--pipeline-stages", default="")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    config_path = Path(args.config).resolve()
    output_root = Path(args.output_root).resolve()

    snapshot = read_json(input_path)
    trade_date = args.trade_date or str(snapshot.get("trade_date") or datetime.now().strftime("%Y-%m-%d"))
    snapshot = _normalize_snapshot(snapshot, trade_date)
    run_id = args.run_id or _build_run_id(trade_date)
    config = load_pipeline_config(config_path)

    output_dir = output_root / run_id
    ctx = RunContext(
        run_id=run_id,
        trade_date=trade_date,
        config=config,
        input_path=input_path,
        output_root=output_root,
        output_dir=output_dir,
        metadata={"config_path": str(config_path)},
    )

    initial_payload = {
        "run_id": run_id,
        "snapshot": snapshot,
        "input_file": str(input_path),
        "config_file": str(config_path),
    }
    if args.pipeline_preset:
        initial_payload["pipeline_preset"] = args.pipeline_preset
    if args.pipeline_stages:
        initial_payload["pipeline_stages"] = args.pipeline_stages
    result = run_pipeline(ctx, initial_payload)
    write_json(output_dir / "final_payload.json", result)

    print(f"AI Trader backend completed: {run_id}")
    print(f"Output directory: {output_dir}")
    print(f"Holding actions: {output_dir / 'holding_actions_t.csv'}")
    print(f"Tech candidates: {output_dir / 'tech_candidates_t.csv'}")
    print(f"AI insights: {output_dir / 'ai_insights_t.csv'}")
    print(f"Orders candidate: {output_dir / 'orders_candidate_t.csv'}")
    print(f"Trade plan: {output_dir / 'trade_plan_t.csv'}")
    print(f"Sim fills: {output_dir / 'sim_fill_t.csv'}")
    print(f"Positions: {output_dir / 'positions_t.csv'}")
    print(f"NAV: {output_dir / 'nav_t.csv'}")
    print(f"Metrics file: {output_dir / 'metrics_t.json'}")
    print(f"Risk report: {output_dir / 'risk_report_t.md'}")


def _build_run_id(trade_date: str) -> str:
    normalized = trade_date.replace("-", "")
    return f"single-day-{normalized}-{datetime.now().strftime('%H%M%S')}"


def _normalize_snapshot(snapshot: dict[str, object], trade_date: str) -> dict[str, object]:
    normalized = dict(snapshot)
    normalized["trade_date"] = trade_date
    return normalized


if __name__ == "__main__":
    main()
