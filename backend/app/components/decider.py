from __future__ import annotations

from typing import Any

from app.adapters import write_csv
from app.contracts import BUY_LIKE_ACTIONS, ORDER_CANDIDATE_FIELDS
from app.utils import clamp, index_by, make_order_id, to_float


def run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    positions_by_symbol = index_by(list(payload.get("positions_prev", [])), "symbol")
    holding_actions = list(payload.get("holding_actions", []))
    holding_actions_by_symbol = index_by(holding_actions, "symbol")
    ai_insights = list(payload.get("ai_insights", []))
    analyst_failed = bool(payload.get("analyst_failed", False))
    risk_mode = str(payload.get("risk_mode", "NEUTRAL"))

    decision_config = ctx.config.get("decision", {})
    holding_config = ctx.config.get("holding", {})
    weight_config = ctx.config.get("weights", {})
    risk_rules = ctx.config.get("risk_rules", {})

    base_w = to_float(weight_config.get("base_w"), 0.08)
    single_stock_cap = to_float(risk_rules.get("single_stock_cap", {}).get("value"), 0.15)
    stop_loss_pct = to_float(holding_config.get("stop_loss_pct"), 0.08)
    take_profit_pct = to_float(holding_config.get("take_profit_pct"), 0.15)
    entry_buffer_bps = to_float(decision_config.get("entry_buffer_bps"), 15.0)
    board_factors = ctx.config.get("a_share", {}).get("position", {}).get("board_risk_factors", {})

    regime_factors = decision_config.get("regime_factors", {})
    regime_factor = to_float(regime_factors.get(risk_mode.lower(), regime_factors.get(risk_mode, 1.0)), 1.0)

    orders_candidate: list[dict[str, Any]] = []
    order_index = 1

    for holding_action in holding_actions:
        action = str(holding_action.get("action_today", "HOLD")).upper()
        last_price = to_float(holding_action.get("last_price"))
        reduce_price = last_price * (1.0 + take_profit_pct * 0.60) if last_price > 0 else 0.0
        exit_price = to_float(holding_action.get("stop_loss"))

        orders_candidate.append(
            {
                "trade_date": ctx.trade_date,
                "order_id": make_order_id(ctx.trade_date, str(holding_action.get("symbol", "")), action, order_index),
                "symbol": holding_action.get("symbol", ""),
                "name": holding_action.get("name", ""),
                "sector": holding_action.get("sector", "UNKNOWN"),
                "board": holding_action.get("board", "UNKNOWN"),
                "action": action,
                "w_ai": 0.0,
                "w_candidate": to_float(holding_action.get("target_weight")),
                "target_weight": to_float(holding_action.get("target_weight")),
                "entry_price": 0.0,
                "stop_loss_price": to_float(holding_action.get("stop_loss")),
                "take_profit_price": to_float(holding_action.get("take_profit")),
                "reduce_price": reduce_price,
                "exit_price": exit_price,
                "reason": holding_action.get("reason", ""),
                "source": "holding_review",
                "confidence": 0.0,
            }
        )
        order_index += 1

    for insight in ai_insights:
        action_hint = str(insight.get("action_hint", "HOLD")).upper()
        symbol = str(insight.get("symbol", ""))
        if action_hint not in BUY_LIKE_ACTIONS:
            continue
        if analyst_failed:
            continue

        confidence = to_float(insight.get("confidence"))
        combined_score = to_float(insight.get("combined_score"))
        board = str(insight.get("board", "MAIN"))
        board_factor = to_float(board_factors.get(board.lower(), board_factors.get(board, 1.0)), 1.0)
        last_price = _resolve_entry_reference_price(payload, symbol)
        entry_price = last_price * (1.0 + entry_buffer_bps / 10000.0) if last_price > 0 else 0.0

        w_ai = base_w * confidence * regime_factor * board_factor * max(0.50, combined_score)
        current_position = positions_by_symbol.get(symbol, {})
        current_weight = to_float(current_position.get("current_weight"))
        current_holding_action = str(holding_actions_by_symbol.get(symbol, {}).get("action_today", "HOLD")).upper()

        action = "BUILD"
        if current_position:
            if action_hint != "ADD" or current_holding_action != "HOLD":
                continue
            incremental_weight = clamp(w_ai, 0.0, max(single_stock_cap - current_weight, 0.0))
            if incremental_weight <= 0.0:
                continue
            w_candidate = clamp(current_weight + incremental_weight, 0.0, single_stock_cap)
            action = "ADD"
        else:
            w_candidate = clamp(w_ai, 0.0, single_stock_cap)
            if w_candidate <= 0.0:
                continue

        orders_candidate.append(
            {
                "trade_date": ctx.trade_date,
                "order_id": make_order_id(ctx.trade_date, symbol, action, order_index),
                "symbol": symbol,
                "name": insight.get("name", ""),
                "sector": insight.get("sector", "UNKNOWN"),
                "board": board,
                "action": action,
                "w_ai": w_ai,
                "w_candidate": w_candidate,
                "target_weight": w_candidate,
                "entry_price": entry_price,
                "stop_loss_price": entry_price * (1.0 - stop_loss_pct) if entry_price > 0 else 0.0,
                "take_profit_price": entry_price * (1.0 + take_profit_pct) if entry_price > 0 else 0.0,
                "reduce_price": entry_price * (1.0 + take_profit_pct * 0.60) if entry_price > 0 else 0.0,
                "exit_price": entry_price * (1.0 - stop_loss_pct) if entry_price > 0 else 0.0,
                "reason": insight.get("thesis", ""),
                "source": insight.get("source", "analyst"),
                "confidence": confidence,
            }
        )
        order_index += 1

    write_csv(ctx.artifact_path("orders_candidate_t.csv"), orders_candidate, ORDER_CANDIDATE_FIELDS)

    next_payload = dict(payload)
    stage_notes = dict(payload.get("stage_notes", {}))
    stage_notes["decider"] = (
        f"orders_candidate={len(orders_candidate)}; analyst_failed={analyst_failed}; risk_mode={risk_mode}"
    )

    next_payload["orders_candidate"] = orders_candidate
    next_payload["stage_notes"] = stage_notes
    return next_payload


def _resolve_entry_reference_price(payload: dict[str, Any], symbol: str) -> float:
    snapshot = payload.get("snapshot", {})
    for raw_candidate in snapshot.get("watchlist", []):
        if str(raw_candidate.get("symbol", "")) == symbol:
            return to_float(raw_candidate.get("last_price"))
    return 0.0
