from __future__ import annotations

import json
from typing import Any

from app.adapters import AnalystLLMError, request_agent_json, require_live_llm
from app.contracts import BUY_LIKE_ACTIONS
from app.pipeline.io import DeciderStageInput
from app.pipeline.outputs import DeciderStageOutput, OrderCandidateRow
from app.pipeline.results import StageResult
from app.utils import clamp, index_by, make_order_id, to_float


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    require_live_llm(ctx.config, "decider")

    stage_input = DeciderStageInput.from_payload(payload)
    positions_by_symbol = index_by(stage_input.portfolio.positions_prev, "symbol")
    holding_actions = list(stage_input.holding_actions)
    ai_insights = list(stage_input.ai_insights)
    risk_mode = stage_input.portfolio.risk_mode

    holding_config = ctx.config.get("holding", {})
    decision_config = ctx.config.get("decision", {})
    risk_rules = ctx.config.get("risk_rules", {})

    single_stock_cap = to_float(risk_rules.get("single_stock_cap", {}).get("value"), 0.15)
    stop_loss_pct = to_float(holding_config.get("stop_loss_pct"), 0.08)
    take_profit_pct = to_float(holding_config.get("take_profit_pct"), 0.15)
    entry_buffer_bps = to_float(decision_config.get("entry_buffer_bps"), 15.0)

    orders_candidate: list[OrderCandidateRow] = []
    order_index = 1

    for holding_action in holding_actions:
        action = str(holding_action.get("action_today", "HOLD")).upper()
        last_price = to_float(holding_action.get("last_price"))
        reduce_price = last_price * (1.0 + take_profit_pct * 0.60) if last_price > 0 else 0.0
        exit_price = to_float(holding_action.get("stop_loss"))

        orders_candidate.append(
            OrderCandidateRow(
                trade_date=ctx.trade_date,
                order_id=make_order_id(ctx.trade_date, str(holding_action.get("symbol", "")), action, order_index),
                symbol=str(holding_action.get("symbol", "")),
                name=str(holding_action.get("name", "")),
                sector=str(holding_action.get("sector", "UNKNOWN")),
                board=str(holding_action.get("board", "UNKNOWN")),
                action=action,
                w_ai=0.0,
                w_candidate=to_float(holding_action.get("target_weight")),
                target_weight=to_float(holding_action.get("target_weight")),
                entry_price=0.0,
                stop_loss_price=to_float(holding_action.get("stop_loss")),
                take_profit_price=to_float(holding_action.get("take_profit")),
                reduce_price=reduce_price,
                exit_price=exit_price,
                reason=str(holding_action.get("reason", "")),
                confidence=0.0,
            )
        )
        order_index += 1

    for insight in ai_insights:
        action_hint = str(insight.get("action_hint", "HOLD")).upper()
        symbol = str(insight.get("symbol", ""))
        if action_hint not in BUY_LIKE_ACTIONS:
            continue

        current_position = positions_by_symbol.get(symbol)
        entry_price = _resolve_entry_reference_price(stage_input, symbol, entry_buffer_bps)
        agent_order = _request_agent_order(
            ctx=ctx,
            insight=insight,
            current_position=current_position,
            risk_mode=risk_mode,
            single_stock_cap=single_stock_cap,
        )
        order_row = _build_agent_order_row(
            ctx=ctx,
            agent_order=agent_order,
            insight=insight,
            current_position=current_position,
            single_stock_cap=single_stock_cap,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            entry_price=entry_price,
            order_index=order_index,
        )
        if order_row is None:
            order_index += 1
            continue
        orders_candidate.append(order_row)
        order_index += 1

    return StageResult(
        updates=DeciderStageOutput(orders_candidate=orders_candidate),
        stage_note=f"llm_agent_decision; orders_candidate={len(orders_candidate)}; risk_mode={risk_mode}",
    )


def _request_agent_order(
    *,
    ctx: Any,
    insight: dict[str, Any],
    current_position: dict[str, Any] | None,
    risk_mode: str,
    single_stock_cap: float,
) -> dict[str, Any]:
    allowed_actions = ["ADD", "SKIP"] if current_position else ["BUILD", "SKIP"]
    payload = {
        "trade_date": ctx.trade_date,
        "risk_mode": risk_mode,
        "allowed_actions": allowed_actions,
        "single_stock_cap": single_stock_cap,
        "current_position": {
            "symbol": current_position.get("symbol"),
            "current_weight": to_float(current_position.get("current_weight")),
            "quantity": to_float(current_position.get("quantity")),
        }
        if current_position
        else {},
        "insight": {
            "symbol": insight.get("symbol"),
            "name": insight.get("name"),
            "sector": insight.get("sector"),
            "board": insight.get("board"),
            "action_hint": insight.get("action_hint"),
            "confidence": to_float(insight.get("confidence")),
            "combined_score": to_float(insight.get("combined_score")),
            "market_technical_score": to_float(insight.get("market_technical_score")),
            "market_data_source": insight.get("market_data_source", "snapshot"),
            "technical_summary": insight.get("technical_summary", ""),
            "thesis": insight.get("thesis"),
            "risk_flags": insight.get("risk_flags"),
        },
    }
    prompt = (
        "你是A股下单决策 agent。请根据研判结论和当前持仓状态，决定是否生成买入类订单。"
        "你只能从 allowed_actions 中选择 action。"
        "如果不应该下单，输出 SKIP。"
        "target_weight 是最终建议目标仓位，必须在 0 到 single_stock_cap 之间。"
        "confidence 必须是 0 到 0.99 之间的小数。"
        "严格输出 JSON，不要输出 markdown。格式为："
        '{"action":"BUILD","target_weight":0.05,"confidence":0.78,"reason":"..."}。\n'
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    response = request_agent_json(ctx.config, prompt)
    if not isinstance(response, dict):
        raise AnalystLLMError("decider agent response must be an object")
    return response


def _build_agent_order_row(
    *,
    ctx: Any,
    agent_order: dict[str, Any],
    insight: dict[str, Any],
    current_position: dict[str, Any] | None,
    single_stock_cap: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    entry_price: float,
    order_index: int,
) -> OrderCandidateRow | None:
    allowed_actions = {"ADD", "SKIP"} if current_position else {"BUILD", "SKIP"}
    action = str(agent_order.get("action", "")).upper()
    if action not in allowed_actions:
        raise AnalystLLMError(f"decider agent invalid action for {insight.get('symbol')}")
    if action == "SKIP":
        return None

    current_weight = to_float((current_position or {}).get("current_weight"))
    target_weight = clamp(
        to_float(agent_order.get("target_weight")),
        current_weight if current_position else 0.0,
        single_stock_cap,
    )
    if current_position and target_weight <= current_weight:
        raise AnalystLLMError(f"decider agent target_weight must exceed current_weight for {insight.get('symbol')}")
    if (not current_position) and target_weight <= 0.0:
        raise AnalystLLMError(f"decider agent target_weight missing for {insight.get('symbol')}")

    confidence = clamp(to_float(agent_order.get("confidence")), 0.0, 0.99)
    reason = str(agent_order.get("reason") or "").strip()
    if not reason:
        raise AnalystLLMError(f"decider agent reason missing for {insight.get('symbol')}")

    return OrderCandidateRow(
        trade_date=ctx.trade_date,
        order_id=make_order_id(ctx.trade_date, str(insight.get("symbol", "")), action, order_index),
        symbol=str(insight.get("symbol", "")),
        name=str(insight.get("name", "")),
        sector=str(insight.get("sector", "UNKNOWN")),
        board=str(insight.get("board", "UNKNOWN")),
        action=action,
        w_ai=target_weight,
        w_candidate=target_weight,
        target_weight=target_weight,
        entry_price=entry_price,
        stop_loss_price=entry_price * (1.0 - stop_loss_pct) if entry_price > 0 else 0.0,
        take_profit_price=entry_price * (1.0 + take_profit_pct) if entry_price > 0 else 0.0,
        reduce_price=entry_price * (1.0 + take_profit_pct * 0.60) if entry_price > 0 else 0.0,
        exit_price=entry_price * (1.0 - stop_loss_pct) if entry_price > 0 else 0.0,
        reason=reason,
        confidence=confidence,
    )


def _resolve_entry_reference_price(stage_input: DeciderStageInput, symbol: str, entry_buffer_bps: float) -> float:
    for raw_candidate in stage_input.candidate_price_rows:
        if str(raw_candidate.get("symbol", "")).strip().upper() == symbol:
            last_price = to_float(raw_candidate.get("last_price"))
            return last_price * (1.0 + entry_buffer_bps / 10000.0) if last_price > 0 else 0.0
    return 0.0
