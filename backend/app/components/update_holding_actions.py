from __future__ import annotations

from typing import Any

from app.a_share import enrich_security_info
from app.adapters import write_csv
from app.contracts import HOLDING_ACTION_FIELDS
from app.utils import resolve_risk_mode, safe_div, to_bool, to_float


def run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("snapshot", {})
    account = _normalize_account(snapshot.get("account", {}))
    total_equity = max(to_float(account.get("total_equity"), 0.0), 1.0)

    risk_mode = resolve_risk_mode(snapshot, ctx.config)
    recent_event_lookup = {str(item.get("symbol", "")): item for item in snapshot.get("recent_events", [])}

    stop_loss_pct = to_float(ctx.config.get("holding", {}).get("stop_loss_pct"), 0.08)
    take_profit_pct = to_float(ctx.config.get("holding", {}).get("take_profit_pct"), 0.15)
    adverse_event_exit_score = to_float(ctx.config.get("holding", {}).get("adverse_event_exit_score"), 0.20)
    reduce_to_weight_factor = to_float(ctx.config.get("holding", {}).get("reduce_to_weight_factor"), 0.60)
    single_stock_cap = to_float(
        ctx.config.get("risk_rules", {}).get("single_stock_cap", {}).get("value"),
        0.15,
    )

    positions_prev: list[dict[str, Any]] = []
    holding_actions: list[dict[str, Any]] = []

    for raw_position in snapshot.get("positions", []):
        security = enrich_security_info(raw_position, ctx.config)
        symbol = security["symbol"]
        if not symbol:
            continue

        quantity = to_float(raw_position.get("quantity"))
        avg_cost = to_float(raw_position.get("avg_cost"))
        last_price = security["last_price"]
        market_value = quantity * last_price
        current_weight = safe_div(market_value, total_equity)
        pnl_pct = safe_div(last_price - avg_cost, avg_cost)
        recent_event = recent_event_lookup.get(symbol, {})
        event_score = to_float(recent_event.get("event_score"), 0.50)
        last_trade_date = str(raw_position.get("last_trade_date", ""))
        t_plus_one_locked = to_bool(raw_position.get("t_plus_one_locked")) or last_trade_date == ctx.trade_date
        available_quantity = max(
            min(security["available_quantity"], quantity),
            0.0,
        )
        if t_plus_one_locked:
            available_quantity = 0.0

        action_today = "HOLD"
        target_weight = current_weight
        risk_level = "LOW"
        reason = f"within_band pnl={pnl_pct:.2%}; event_score={event_score:.2f}"

        if event_score <= adverse_event_exit_score or pnl_pct <= -stop_loss_pct:
            action_today = "EXIT"
            target_weight = 0.0
            risk_level = "HIGH"
            reason = f"exit_guard pnl={pnl_pct:.2%}; event_score={event_score:.2f}"
        elif pnl_pct >= take_profit_pct:
            action_today = "REDUCE"
            target_weight = min(current_weight * reduce_to_weight_factor, single_stock_cap)
            risk_level = "MEDIUM"
            reason = f"take_profit pnl={pnl_pct:.2%}; target_weight={target_weight:.2%}"
        elif current_weight > single_stock_cap:
            action_today = "REDUCE"
            target_weight = single_stock_cap
            risk_level = "MEDIUM"
            reason = f"rebalance_to_cap current_weight={current_weight:.2%}; cap={single_stock_cap:.2%}"
        elif current_weight >= single_stock_cap * 0.95:
            risk_level = "MEDIUM"
            reason = f"near_single_cap current_weight={current_weight:.2%}; pnl={pnl_pct:.2%}"

        normalized_position = {
            "trade_date": ctx.trade_date,
            "symbol": symbol,
            "name": security["name"],
            "sector": security["industry"],
            "board": security["board"],
            "quantity": quantity,
            "available_quantity": available_quantity,
            "avg_cost": avg_cost,
            "prev_close": security["prev_close"],
            "last_price": last_price,
            "upper_limit": security["upper_limit"] or 0.0,
            "lower_limit": security["lower_limit"] or 0.0,
            "market_value": market_value,
            "current_weight": current_weight,
            "unrealized_pnl_pct": pnl_pct,
            "is_st": security["is_st"],
            "suspended": security["suspended"],
            "list_days": security["list_days"],
            "last_trade_date": last_trade_date,
            "t_plus_one_locked": t_plus_one_locked,
        }
        positions_prev.append(normalized_position)

        holding_actions.append(
            {
                "trade_date": ctx.trade_date,
                "symbol": symbol,
                "name": normalized_position["name"],
                "sector": normalized_position["sector"],
                "board": normalized_position["board"],
                "quantity": quantity,
                "available_quantity": available_quantity,
                "avg_cost": avg_cost,
                "prev_close": normalized_position["prev_close"],
                "last_price": last_price,
                "upper_limit": normalized_position["upper_limit"],
                "lower_limit": normalized_position["lower_limit"],
                "current_weight": current_weight,
                "action_today": action_today,
                "target_weight": target_weight,
                "stop_loss": avg_cost * (1.0 - stop_loss_pct) if avg_cost > 0 else 0.0,
                "take_profit": avg_cost * (1.0 + take_profit_pct) if avg_cost > 0 else 0.0,
                "risk_level": risk_level,
                "is_st": security["is_st"],
                "suspended": security["suspended"],
                "list_days": security["list_days"],
                "reason": reason,
                "last_trade_date": normalized_position["last_trade_date"],
                "t_plus_one_locked": normalized_position["t_plus_one_locked"],
            }
        )

    write_csv(ctx.artifact_path("holding_actions_t.csv"), holding_actions, HOLDING_ACTION_FIELDS)

    next_payload = dict(payload)
    stage_notes = dict(payload.get("stage_notes", {}))
    stage_notes["update_holding_actions"] = f"positions={len(positions_prev)}; risk_mode={risk_mode}"

    next_payload["account"] = account
    next_payload["risk_mode"] = risk_mode
    next_payload["positions_prev"] = positions_prev
    next_payload["positions"] = positions_prev
    next_payload["holding_actions"] = holding_actions
    next_payload["stage_notes"] = stage_notes
    return next_payload


def _normalize_account(raw_account: dict[str, Any]) -> dict[str, Any]:
    cash = to_float(raw_account.get("cash"))
    total_equity = to_float(raw_account.get("total_equity"))
    prev_total_equity = to_float(raw_account.get("prev_total_equity"), total_equity)
    initial_equity = to_float(raw_account.get("initial_equity"), prev_total_equity or total_equity)
    return {
        "cash": cash,
        "total_equity": total_equity,
        "prev_total_equity": prev_total_equity,
        "initial_equity": initial_equity,
        "portfolio_drawdown_pct": to_float(raw_account.get("portfolio_drawdown_pct")),
    }
