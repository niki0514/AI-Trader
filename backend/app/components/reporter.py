from __future__ import annotations

from typing import Any

from app.adapters import write_json, write_text
from app.contracts import SELL_LIKE_ACTIONS
from app.utils import compute_sharpe_ratio, index_by, to_float


def run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    trade_plan = list(payload.get("trade_plan", []))
    sim_fill = list(payload.get("sim_fill", []))
    positions_prev = index_by(list(payload.get("positions_prev", [])), "symbol")
    positions = list(payload.get("positions", []))
    nav = list(payload.get("nav", []))
    risk_events = list(payload.get("risk_events", []))
    nav_row = nav[-1] if nav else {}

    metrics = _build_metrics(payload, trade_plan, sim_fill, positions_prev, nav)
    risk_report = _build_risk_report(ctx, payload, trade_plan, sim_fill, positions, nav_row, risk_events, metrics)

    metrics_path = ctx.artifact_path("metrics_t.json")
    risk_report_path = ctx.artifact_path("risk_report_t.md")

    write_json(metrics_path, metrics)
    write_text(risk_report_path, risk_report)

    next_payload = dict(payload)
    stage_notes = dict(payload.get("stage_notes", {}))
    stage_notes["reporter"] = (
        f"metrics_ready; intercepts={metrics['risk_intercept_count']}; filled={metrics['filled_order_count']}"
    )

    next_payload["metrics"] = metrics
    next_payload["report_files"] = {
        "metrics_t.json": str(metrics_path),
        "risk_report_t.md": str(risk_report_path),
    }
    next_payload["stage_notes"] = stage_notes
    return next_payload


def _build_metrics(
    payload: dict[str, Any],
    trade_plan: list[dict[str, Any]],
    sim_fill: list[dict[str, Any]],
    positions_prev: dict[str, dict[str, Any]],
    nav: list[dict[str, Any]],
) -> dict[str, Any]:
    nav_row = nav[-1] if nav else {}
    daily_returns = [to_float(item.get("daily_return")) for item in nav if item.get("daily_return") not in {"", None}]
    filled_orders = [row for row in sim_fill if row.get("status") == "FILLED"]

    profitable_sells = 0
    sell_count = 0
    for fill in filled_orders:
        if str(fill.get("action", "")).upper() not in SELL_LIKE_ACTIONS:
            continue
        sell_count += 1
        avg_cost = to_float(positions_prev.get(str(fill.get("symbol", "")), {}).get("avg_cost"))
        if to_float(fill.get("fill_price")) > avg_cost:
            profitable_sells += 1

    risk_intercept_count = len(
        [
            row
            for row in trade_plan
            if str(row.get("status", "")).upper() == "REJECTED" or str(row.get("cap_hit_reason", "")).strip()
        ]
    )

    return {
        "run_id": payload.get("run_id", ""),
        "trade_date": payload.get("snapshot", {}).get("trade_date") or nav_row.get("trade_date", ""),
        "daily_return": to_float(nav_row.get("daily_return")),
        "cum_return": to_float(nav_row.get("cum_return")),
        "max_drawdown": to_float(nav_row.get("max_drawdown")),
        "trading_fees": to_float(nav_row.get("trading_fees")),
        "sharpe_ratio": compute_sharpe_ratio(daily_returns),
        "win_rate": profitable_sells / sell_count if sell_count else 0.0,
        "risk_intercept_count": risk_intercept_count,
        "filled_order_count": len(filled_orders),
        "accepted_order_count": len([row for row in trade_plan if row.get("status") == "ACCEPTED"]),
        "limit_no_fill_count": len(
            [row for row in sim_fill if "limit_" in str(row.get("note", "")) and row.get("status") != "FILLED"]
        ),
        "total_buy_orders": len([row for row in filled_orders if str(row.get("action", "")).upper() in {"BUILD", "ADD"}]),
        "total_sell_orders": len([row for row in filled_orders if str(row.get("action", "")).upper() in SELL_LIKE_ACTIONS]),
        "analyst_failed": bool(payload.get("analyst_failed", False)),
        "selector_failed": bool(payload.get("selector_failed", False)),
        "risk_mode": str(payload.get("risk_mode", "NEUTRAL")),
    }


def _build_risk_report(
    ctx: Any,
    payload: dict[str, Any],
    trade_plan: list[dict[str, Any]],
    sim_fill: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    nav_row: dict[str, Any],
    risk_events: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    rejected_lines = [
        f"- {item['symbol']} {item['action']} -> {item['status']} ({item['reason']})"
        for item in risk_events
    ] or ["- no risk intercepts"]

    fill_lines = [
        f"- {row['symbol']} {row['action']} qty={to_float(row['quantity']):.2f} "
        f"status={row['status']} fee={to_float(row.get('total_fee')):.2f} note={row['note']}"
        for row in sim_fill
    ] or ["- no fills"]

    position_lines = [
        f"- {row['symbol']} board={row.get('board', 'UNKNOWN')} weight={to_float(row['weight']):.2%} "
        f"mv={to_float(row['market_value']):.2f}"
        for row in positions
    ] or ["- no positions"]

    return "\n".join(
        [
            "# AI Trader Risk Report",
            "",
            f"- run_id: {ctx.run_id}",
            f"- trade_date: {ctx.trade_date}",
            f"- risk_mode: {payload.get('risk_mode', 'NEUTRAL')}",
            f"- total_equity: {to_float(nav_row.get('total_equity')):.2f}",
            f"- daily_return: {metrics['daily_return']:.4f}",
            f"- cum_return: {metrics['cum_return']:.4f}",
            f"- max_drawdown: {metrics['max_drawdown']:.4f}",
            f"- trading_fees: {metrics['trading_fees']:.2f}",
            f"- risk_intercept_count: {metrics['risk_intercept_count']}",
            "",
            "## Risk Events",
            *rejected_lines,
            "",
            "## Execution",
            *fill_lines,
            "",
            "## End Positions",
            *position_lines,
            "",
            "## Stage Notes",
            *[f"- {stage}: {note}" for stage, note in payload.get("stage_notes", {}).items()],
            "",
        ]
    )
