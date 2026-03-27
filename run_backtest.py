from __future__ import annotations

import argparse
import copy
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters import read_json, write_csv, write_json, write_text
from app.config import load_pipeline_config
from app.contracts import NAV_FIELDS, SIM_FILL_FIELDS
from app.pipeline.context import RunContext
from app.runner import run_pipeline
from app.utils import compute_max_drawdown, compute_sharpe_ratio, safe_div, to_bool, to_float


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI Trader backtest.")
    parser.add_argument(
        "--manifest",
        default=str(BACKEND_DIR / "examples" / "input" / "backtest_manifest.json"),
    )
    parser.add_argument("--config", default=str(BACKEND_DIR / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--output-root", default=str(BACKEND_DIR / "outputs" / "backtests"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--pipeline-preset", default="")
    parser.add_argument("--pipeline-stages", default="")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    config_path = Path(args.config).resolve()
    output_root = Path(args.output_root).resolve()
    manifest = read_json(manifest_path)
    config = load_pipeline_config(config_path)

    run_id = args.run_id or _build_run_id(manifest.get("name", "backtest"))
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    snapshots = _load_snapshots(manifest_path, manifest)
    if not snapshots:
        raise ValueError("No snapshots loaded for backtest.")

    carry_portfolio_state = to_bool(manifest.get("portfolio_state_carry"), True)
    portfolio_state = _init_portfolio_state(snapshots[0]) if carry_portfolio_state else None

    daily_nav_rows: list[dict[str, Any]] = []
    all_fill_rows: list[dict[str, Any]] = []
    day_summaries: list[dict[str, Any]] = []

    for index, base_snapshot in enumerate(snapshots, start=1):
        snapshot = copy.deepcopy(base_snapshot)
        trade_date = str(snapshot.get("trade_date", ""))

        if carry_portfolio_state and portfolio_state is not None:
            snapshot = _inject_portfolio_state(snapshot, portfolio_state)

        day_output_dir = run_dir / "days" / trade_date
        ctx = RunContext(
            run_id=f"{run_id}-{trade_date}",
            trade_date=trade_date,
            config=config,
            input_path=manifest_path,
            output_root=output_root,
            output_dir=day_output_dir,
            metadata={
                "config_path": str(config_path),
                "manifest_path": str(manifest_path),
                "backtest_day_index": index,
                "portfolio_state_carry": carry_portfolio_state,
            },
        )
        result = run_pipeline(
            ctx,
            {
                "run_id": ctx.run_id,
                "snapshot": snapshot,
                "input_file": str(manifest_path),
                "config_file": str(config_path),
                "backtest_mode": True,
                "pipeline_preset": args.pipeline_preset,
                "pipeline_stages": args.pipeline_stages,
            },
        )
        write_json(day_output_dir / "final_payload.json", result)

        nav_row = dict((result.get("nav") or [{}])[-1])
        metrics = dict(result.get("metrics", {}))
        nav_row["risk_intercept_count"] = metrics.get("risk_intercept_count", 0)
        nav_row["filled_order_count"] = metrics.get("filled_order_count", nav_row.get("filled_order_count", 0))
        daily_nav_rows.append(nav_row)
        all_fill_rows.extend(list(result.get("sim_fill", [])))
        day_summaries.append(
            {
                "trade_date": trade_date,
                "run_id": ctx.run_id,
                "daily_return": to_float(metrics.get("daily_return")),
                "cum_return": to_float(metrics.get("cum_return")),
                "risk_intercept_count": int(metrics.get("risk_intercept_count", 0)),
                "filled_order_count": int(metrics.get("filled_order_count", 0)),
                "end_total_equity": to_float(nav_row.get("total_equity")),
                "end_cash": to_float(nav_row.get("cash")),
            }
        )

        if carry_portfolio_state and portfolio_state is not None:
            portfolio_state = _advance_portfolio_state(portfolio_state, result)

    summary = _build_summary(
        run_id=run_id,
        manifest=manifest,
        daily_nav_rows=daily_nav_rows,
        day_summaries=day_summaries,
        portfolio_state_carry=carry_portfolio_state,
    )
    report = _build_report(run_id, manifest, summary, day_summaries)

    write_csv(run_dir / "backtest_nav.csv", daily_nav_rows, NAV_FIELDS + ["risk_intercept_count"])
    write_csv(run_dir / "backtest_fills.csv", all_fill_rows, SIM_FILL_FIELDS)
    write_json(run_dir / "backtest_summary.json", summary)
    write_text(run_dir / "walk_forward_report.md", report)
    if carry_portfolio_state and portfolio_state is not None:
        write_json(run_dir / "backtest_state_final.json", portfolio_state)

    print(f"AI Trader backtest completed: {run_id}")
    print(f"Output directory: {run_dir}")
    print(f"Backtest NAV: {run_dir / 'backtest_nav.csv'}")
    print(f"Backtest fills: {run_dir / 'backtest_fills.csv'}")
    print(f"Backtest summary: {run_dir / 'backtest_summary.json'}")
    print(f"Walk-forward report: {run_dir / 'walk_forward_report.md'}")


def _load_snapshots(manifest_path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    mode = str(manifest.get("mode", "synthetic_from_base_snapshot"))

    if mode == "synthetic_from_base_snapshot":
        base_snapshot_ref = str(manifest.get("base_snapshot", "daily_snapshot.json"))
        base_snapshot_path = (manifest_path.parent / base_snapshot_ref).resolve()
        base_snapshot = read_json(base_snapshot_path)
        trade_dates = list(manifest.get("trade_dates", []))
        if not trade_dates:
            raise ValueError("Manifest missing trade_dates.")

        return [
            _synthetic_snapshot(base_snapshot, trade_date=str(trade_date), index=index)
            for index, trade_date in enumerate(trade_dates)
        ]

    if mode == "snapshot_files":
        snapshot_refs = list(manifest.get("snapshots", []))
        if not snapshot_refs:
            raise ValueError("Manifest missing snapshots for mode=snapshot_files.")
        snapshots: list[dict[str, Any]] = []
        for ref in snapshot_refs:
            snapshot_path = (manifest_path.parent / str(ref)).resolve()
            snapshot = read_json(snapshot_path)
            snapshots.append(snapshot)
        return snapshots

    raise ValueError(f"Unsupported backtest mode: {mode}")


def _synthetic_snapshot(base_snapshot: dict[str, Any], trade_date: str, index: int) -> dict[str, Any]:
    snapshot = copy.deepcopy(base_snapshot)
    snapshot["trade_date"] = trade_date

    price_shifts = [-0.010, 0.012, 0.008, -0.006, 0.015, -0.004, 0.011]
    event_shifts = [-0.03, 0.02, 0.01, -0.01, 0.03, -0.02, 0.01]
    price_shift = price_shifts[index % len(price_shifts)]
    event_shift = event_shifts[index % len(event_shifts)]

    account = dict(snapshot.get("account", {}))
    base_total_equity = to_float(account.get("total_equity"), 120000.0)
    account["prev_total_equity"] = round(base_total_equity * (1.0 + price_shift / 2.0), 2)
    account["total_equity"] = round(base_total_equity * (1.0 + price_shift), 2)
    snapshot["account"] = account

    for collection_name in ("positions", "watchlist"):
        for item_index, item in enumerate(snapshot.get(collection_name, []), start=1):
            symbol_bias = (item_index % 3 - 1) * 0.003
            last_price = to_float(item.get("last_price"))
            item["last_price"] = round(last_price * (1.0 + price_shift + symbol_bias), 4)
            if "momentum_score" in item:
                item["momentum_score"] = _bounded_score(to_float(item.get("momentum_score")) + event_shift + symbol_bias)
            if "breakout_score" in item:
                item["breakout_score"] = _bounded_score(to_float(item.get("breakout_score")) + event_shift / 2.0)
            if "liquidity_score" in item:
                item["liquidity_score"] = _bounded_score(to_float(item.get("liquidity_score")) + 0.01)

    for event_index, item in enumerate(snapshot.get("recent_events", []), start=1):
        symbol_bias = (event_index % 2) * 0.02 - 0.01
        item["event_score"] = _bounded_score(to_float(item.get("event_score"), 0.5) + event_shift + symbol_bias)

    for item in snapshot.get("fundamentals", []):
        for key in ("growth_score", "quality_score", "valuation_score"):
            if key in item:
                item[key] = _bounded_score(to_float(item.get(key), 0.5) + event_shift / 3.0)

    return snapshot


def _init_portfolio_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    account = dict(snapshot.get("account", {}))
    cash = to_float(account.get("cash"))
    total_equity = to_float(account.get("total_equity"))
    prev_total_equity = to_float(account.get("prev_total_equity"), total_equity)
    initial_equity = to_float(account.get("initial_equity"), prev_total_equity or total_equity)
    peak_equity = max(total_equity, prev_total_equity, initial_equity)

    return {
        "cash": cash,
        "prev_total_equity": prev_total_equity,
        "initial_equity": initial_equity,
        "peak_equity": peak_equity,
        "positions": _normalize_positions(snapshot.get("positions", []), fallback_trade_date=str(snapshot.get("trade_date", ""))),
    }


def _inject_portfolio_state(snapshot: dict[str, Any], portfolio_state: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(snapshot)
    price_lookup = _build_price_lookup(enriched)

    carried_positions: list[dict[str, Any]] = []
    for position in portfolio_state.get("positions", []):
        symbol = str(position.get("symbol", ""))
        quantity = to_float(position.get("quantity"))
        if quantity <= 0 or not symbol:
            continue

        last_price = price_lookup.get(symbol, to_float(position.get("last_price")))
        avg_cost = to_float(position.get("avg_cost"))
        carried_positions.append(
            {
                "symbol": symbol,
                "name": position.get("name", ""),
                "sector": position.get("sector", "UNKNOWN"),
                "quantity": quantity,
                "avg_cost": avg_cost,
                "last_price": last_price,
                "last_trade_date": position.get("last_trade_date", ""),
                "t_plus_one_locked": bool(position.get("t_plus_one_locked", False)),
            }
        )

    cash = to_float(portfolio_state.get("cash"))
    market_value = sum(to_float(item.get("quantity")) * to_float(item.get("last_price")) for item in carried_positions)
    total_equity = cash + market_value
    prev_total_equity = to_float(portfolio_state.get("prev_total_equity"), total_equity)
    initial_equity = to_float(portfolio_state.get("initial_equity"), prev_total_equity or total_equity)
    peak_equity = max(to_float(portfolio_state.get("peak_equity"), total_equity), total_equity)
    drawdown = safe_div(peak_equity - total_equity, peak_equity or total_equity)

    account = dict(enriched.get("account", {}))
    account.update(
        {
            "cash": cash,
            "total_equity": total_equity,
            "prev_total_equity": prev_total_equity,
            "initial_equity": initial_equity,
            "portfolio_drawdown_pct": drawdown,
        }
    )

    enriched["positions"] = carried_positions
    enriched["account"] = account
    return enriched


def _advance_portfolio_state(portfolio_state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    nav_row = dict((result.get("nav") or [{}])[-1])
    total_equity = to_float(nav_row.get("total_equity"), to_float(portfolio_state.get("prev_total_equity")))
    cash = to_float(nav_row.get("cash"), to_float(portfolio_state.get("cash")))
    peak_equity = max(to_float(portfolio_state.get("peak_equity"), total_equity), total_equity)

    positions = _normalize_positions(
        result.get("positions", []),
        fallback_trade_date=str(nav_row.get("trade_date", "")),
    )

    return {
        "cash": cash,
        "prev_total_equity": total_equity,
        "initial_equity": to_float(portfolio_state.get("initial_equity"), total_equity),
        "peak_equity": peak_equity,
        "positions": positions,
    }


def _normalize_positions(raw_positions: Any, fallback_trade_date: str = "") -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for raw in list(raw_positions or []):
        symbol = str(raw.get("symbol", "")).strip()
        quantity = to_float(raw.get("quantity"))
        if not symbol or quantity <= 0:
            continue
        positions.append(
            {
                "symbol": symbol,
                "name": raw.get("name", ""),
                "sector": raw.get("sector", "UNKNOWN"),
                "quantity": quantity,
                "avg_cost": to_float(raw.get("avg_cost")),
                "last_price": to_float(raw.get("last_price")),
                "last_trade_date": str(raw.get("last_trade_date") or fallback_trade_date),
                "t_plus_one_locked": bool(raw.get("t_plus_one_locked", False)),
            }
        )
    return positions


def _build_price_lookup(snapshot: dict[str, Any]) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for collection_name in ("positions", "watchlist"):
        for item in snapshot.get(collection_name, []):
            symbol = str(item.get("symbol", "")).strip()
            if not symbol:
                continue
            price = to_float(item.get("last_price"))
            if price > 0:
                lookup[symbol] = price
    return lookup


def _bounded_score(value: float) -> float:
    return round(max(0.05, min(0.95, value)), 4)


def _build_summary(
    run_id: str,
    manifest: dict[str, Any],
    daily_nav_rows: list[dict[str, Any]],
    day_summaries: list[dict[str, Any]],
    portfolio_state_carry: bool,
) -> dict[str, Any]:
    daily_returns = [to_float(row.get("daily_return")) for row in daily_nav_rows]
    equity_curve = [to_float(row.get("total_equity")) for row in daily_nav_rows]

    compounded = 1.0
    for daily_return in daily_returns:
        compounded *= 1.0 + daily_return

    positive_days = len([value for value in daily_returns if value > 0])
    return {
        "run_id": run_id,
        "manifest_name": manifest.get("name", "backtest"),
        "mode": manifest.get("mode", "synthetic_from_base_snapshot"),
        "day_count": len(daily_nav_rows),
        "trade_date_start": day_summaries[0]["trade_date"] if day_summaries else "",
        "trade_date_end": day_summaries[-1]["trade_date"] if day_summaries else "",
        "cum_return": compounded - 1.0,
        "max_drawdown": compute_max_drawdown(equity_curve),
        "sharpe_ratio": compute_sharpe_ratio(daily_returns),
        "win_rate": positive_days / len(daily_returns) if daily_returns else 0.0,
        "portfolio_state_carry": portfolio_state_carry,
        "engine_status": "stateful_ready" if portfolio_state_carry else "day_isolated",
        "notes": [
            "Runs the single-day pipeline over manifest snapshots.",
            "If portfolio_state_carry=true, cash/positions are carried across days.",
        ],
    }


def _build_report(
    run_id: str,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    day_summaries: list[dict[str, Any]],
) -> str:
    day_lines = [
        f"- {row['trade_date']}: daily_return={row['daily_return']:.4f}, "
        f"risk_intercepts={row['risk_intercept_count']}, filled_orders={row['filled_order_count']}, "
        f"end_equity={row['end_total_equity']:.2f}"
        for row in day_summaries
    ] or ["- no days"]

    return "\n".join(
        [
            "# AI Trader Backtest Report",
            "",
            f"- run_id: {run_id}",
            f"- manifest: {manifest.get('name', 'backtest')}",
            f"- mode: {summary['mode']}",
            f"- day_count: {summary['day_count']}",
            f"- cum_return: {summary['cum_return']:.4f}",
            f"- max_drawdown: {summary['max_drawdown']:.4f}",
            f"- sharpe_ratio: {summary['sharpe_ratio']:.4f}",
            f"- win_rate: {summary['win_rate']:.4f}",
            f"- portfolio_state_carry: {summary['portfolio_state_carry']}",
            f"- engine_status: {summary['engine_status']}",
            "",
            "## Daily Summary",
            *day_lines,
            "",
            "## Notes",
            *[f"- {note}" for note in summary["notes"]],
            "",
        ]
    )


def _build_run_id(manifest_name: str) -> str:
    normalized = str(manifest_name).replace(" ", "-").lower()
    return f"backtest-{normalized}-{datetime.now().strftime('%H%M%S')}"


if __name__ == "__main__":
    main()
