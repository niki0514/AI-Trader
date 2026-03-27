from __future__ import annotations

import json
from typing import Any

from app.a_share import enrich_security_info
from app.adapters import AnalystLLMError, request_agent_json, require_live_llm
from app.pipeline.io import HoldingReviewStageInput
from app.pipeline.outputs import HoldingActionRow, HoldingReviewStageOutput, PositionSnapshotRow
from app.pipeline.results import StageResult
from app.utils import clamp, resolve_risk_mode, safe_div, to_bool, to_float


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    require_live_llm(ctx.config, "update_holding_actions")

    stage_input = HoldingReviewStageInput.from_payload(payload)
    snapshot = stage_input.snapshots.effective_snapshot
    account = _normalize_account(snapshot.get("account", {}))
    risk_mode = resolve_risk_mode(snapshot, ctx.config)

    positions_prev = _normalize_positions(ctx=ctx, snapshot=snapshot, account=account)
    holding_actions = _request_holding_actions(
        ctx=ctx,
        snapshot=snapshot,
        account=account,
        risk_mode=risk_mode,
        positions_prev=positions_prev,
    )

    return StageResult(
        updates=HoldingReviewStageOutput(
            account=account,
            risk_mode=risk_mode,
            positions_prev=positions_prev,
            positions=positions_prev,
            holding_actions=holding_actions,
        ),
        stage_note=f"llm_agent_holding_review; positions={len(positions_prev)}; risk_mode={risk_mode}",
    )


def _normalize_positions(
    *,
    ctx: Any,
    snapshot: dict[str, Any],
    account: dict[str, Any],
) -> list[PositionSnapshotRow]:
    total_equity = max(to_float(account.get("total_equity"), 0.0), 1.0)
    recent_event_lookup = {str(item.get("symbol", "")): item for item in snapshot.get("recent_events", [])}

    positions_prev: list[PositionSnapshotRow] = []
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
        available_quantity = max(min(security["available_quantity"], quantity), 0.0)
        if t_plus_one_locked:
            available_quantity = 0.0

        positions_prev.append(
            PositionSnapshotRow(
                trade_date=ctx.trade_date,
                symbol=symbol,
                name=security["name"],
                sector=security["industry"],
                board=security["board"],
                quantity=quantity,
                available_quantity=available_quantity,
                avg_cost=avg_cost,
                prev_close=security["prev_close"],
                last_price=last_price,
                upper_limit=security["upper_limit"] or 0.0,
                lower_limit=security["lower_limit"] or 0.0,
                market_value=market_value,
                current_weight=current_weight,
                unrealized_pnl_pct=pnl_pct,
                is_st=security["is_st"],
                suspended=security["suspended"],
                list_days=to_float(security["list_days"]),
                last_trade_date=last_trade_date,
                t_plus_one_locked=t_plus_one_locked,
                event_score=event_score,
            )
        )
    return positions_prev


def _request_holding_actions(
    *,
    ctx: Any,
    snapshot: dict[str, Any],
    account: dict[str, Any],
    risk_mode: str,
    positions_prev: list[PositionSnapshotRow],
) -> list[HoldingActionRow]:
    if not positions_prev:
        return []

    stop_loss_pct = to_float(ctx.config.get("holding", {}).get("stop_loss_pct"), 0.08)
    take_profit_pct = to_float(ctx.config.get("holding", {}).get("take_profit_pct"), 0.15)
    single_stock_cap = to_float(
        ctx.config.get("risk_rules", {}).get("single_stock_cap", {}).get("value"),
        0.15,
    )

    prompt_payload = {
        "trade_date": ctx.trade_date,
        "risk_mode": risk_mode,
        "policy": {
            "allowed_actions": ["HOLD", "REDUCE", "EXIT"],
            "single_stock_cap": single_stock_cap,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        },
        "account": {
            "cash": to_float(account.get("cash")),
            "total_equity": to_float(account.get("total_equity")),
            "portfolio_drawdown_pct": to_float(account.get("portfolio_drawdown_pct")),
        },
        "positions": [
            {
                "symbol": row.symbol,
                "name": row.name,
                "sector": row.sector,
                "board": row.board,
                "current_weight": row.current_weight,
                "unrealized_pnl_pct": row.unrealized_pnl_pct,
                "available_quantity": row.available_quantity,
                "event_score": row.event_score,
                "t_plus_one_locked": row.t_plus_one_locked,
                "is_st": row.is_st,
                "suspended": row.suspended,
            }
            for row in positions_prev
        ],
        "recent_events": list(snapshot.get("recent_events", [])),
    }
    prompt = (
        "你是A股持仓动作 agent。请只基于输入内容判断已有持仓今天应该 HOLD、REDUCE 还是 EXIT。"
        "你必须覆盖每一个持仓 symbol。"
        "target_weight 必须是 0 到 current_weight 之间的小数。"
        "risk_level 只能是 LOW、MEDIUM、HIGH。"
        "严格输出 JSON，不要输出 markdown。格式为："
        '{"decisions":[{"symbol":"600519.SH","action_today":"REDUCE","target_weight":0.12,'
        '"risk_level":"MEDIUM","reason":"..."}]}。\n'
        f"{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    response = request_agent_json(ctx.config, prompt)
    if not isinstance(response, dict):
        raise AnalystLLMError("holding action agent response must be an object")
    decisions = response.get("decisions", [])
    if not isinstance(decisions, list):
        raise AnalystLLMError("holding action agent response missing decisions list")

    agent_by_symbol = {
        str(item.get("symbol", "")).strip(): item
        for item in decisions
        if isinstance(item, dict) and str(item.get("symbol", "")).strip()
    }

    allowed_actions = {"HOLD", "REDUCE", "EXIT"}
    allowed_risk_levels = {"LOW", "MEDIUM", "HIGH"}
    rows: list[HoldingActionRow] = []
    for position in positions_prev:
        symbol = position.symbol.strip()
        agent_row = agent_by_symbol.get(symbol)
        if not agent_row:
            raise AnalystLLMError(f"holding action agent missing symbol {symbol}")

        current_weight = position.current_weight
        action_today = str(agent_row.get("action_today", "")).upper()
        if action_today not in allowed_actions:
            raise AnalystLLMError(f"holding action agent invalid action for {symbol}")

        if action_today == "EXIT":
            target_weight = 0.0
        elif action_today == "HOLD":
            target_weight = current_weight
        else:
            target_weight = clamp(to_float(agent_row.get("target_weight")), 0.0, current_weight)

        risk_level = str(agent_row.get("risk_level", "")).upper()
        if risk_level not in allowed_risk_levels:
            raise AnalystLLMError(f"holding action agent invalid risk level for {symbol}")

        avg_cost = position.avg_cost
        rows.append(
            HoldingActionRow(
                trade_date=ctx.trade_date,
                symbol=symbol,
                name=position.name,
                sector=position.sector,
                board=position.board,
                quantity=position.quantity,
                available_quantity=position.available_quantity,
                avg_cost=avg_cost,
                prev_close=position.prev_close,
                last_price=position.last_price,
                upper_limit=position.upper_limit,
                lower_limit=position.lower_limit,
                current_weight=current_weight,
                action_today=action_today,
                target_weight=target_weight,
                stop_loss=avg_cost * (1.0 - stop_loss_pct) if avg_cost > 0 else 0.0,
                take_profit=avg_cost * (1.0 + take_profit_pct) if avg_cost > 0 else 0.0,
                risk_level=risk_level,
                is_st=position.is_st,
                suspended=position.suspended,
                list_days=position.list_days,
                reason=str(agent_row.get("reason") or ""),
                last_trade_date=position.last_trade_date,
                t_plus_one_locked=position.t_plus_one_locked,
            )
        )
    return rows


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
