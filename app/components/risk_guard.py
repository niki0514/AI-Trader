from __future__ import annotations

from typing import Any

from app.a_share import board_exposure_key, is_limit_down, is_limit_up
from app.contracts import BUY_LIKE_ACTIONS, SELL_LIKE_ACTIONS
from app.pipeline.io import RiskGuardStageInput
from app.pipeline.outputs import RiskEventRow, RiskGuardStageOutput, TradePlanRow
from app.pipeline.results import StageResult
from app.utils import index_by, to_bool, to_float


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    stage_input = RiskGuardStageInput.from_payload(payload)
    orders_candidate = list(stage_input.orders_candidate)
    try:
        trade_plan, risk_events = _build_trade_plan(ctx, stage_input)
        risk_guard_failed = False
        stage_label = "risk_rules_applied"
    except Exception as exc:
        trade_plan, risk_events = _fallback_trade_plan(ctx, orders_candidate, str(exc))
        risk_guard_failed = True
        stage_label = "risk_guard_fallback"

    return StageResult(
        updates=RiskGuardStageOutput(
            trade_plan=trade_plan,
            risk_events=risk_events,
            risk_guard_failed=risk_guard_failed,
        ),
        stage_note=(
            f"{stage_label}; accepted={len([row for row in trade_plan if row.status == 'ACCEPTED'])}; "
            f"rejected={len([row for row in trade_plan if row.status == 'REJECTED'])}"
        ),
    )


def _build_trade_plan(
    ctx: Any,
    stage_input: RiskGuardStageInput,
) -> tuple[list[TradePlanRow], list[RiskEventRow]]:
    positions_by_symbol = index_by(stage_input.portfolio.positions_prev, "symbol")
    tech_candidates_by_symbol = index_by(stage_input.tech_candidates, "symbol")
    account = stage_input.portfolio.account
    risk_mode = stage_input.portfolio.risk_mode

    risk_config = ctx.config.get("risk", {})
    risk_rules = ctx.config.get("risk_rules", {})
    portfolio_caps = risk_config.get("mode_caps", {})
    portfolio_cap = to_float(portfolio_caps.get(risk_mode.lower(), portfolio_caps.get(risk_mode, 0.50)), 0.50)

    single_stock_cap = to_float(risk_rules.get("single_stock_cap", {}).get("value"), 0.15)
    industry_cap = to_float(risk_rules.get("industry_cap", {}).get("value"), 0.30)
    liquidity_cap_default = to_float(risk_rules.get("liquidity_cap", {}).get("value"), 0.12)
    t_plus_one_enabled = to_bool(risk_rules.get("t_plus_one", {}).get("enabled"), True)
    drawdown_rule = risk_rules.get("drawdown_guard", {})
    a_share_risk = ctx.config.get("a_share", {}).get("risk", {})
    board_caps_config = a_share_risk.get("board_caps", {})
    buy_reject_if_st = to_bool(a_share_risk.get("buy_reject_if_st"), True)
    buy_reject_if_suspended = to_bool(a_share_risk.get("buy_reject_if_suspended"), True)
    buy_reject_if_limit_up = to_bool(a_share_risk.get("buy_reject_if_limit_up"), True)
    min_listing_days = to_float(a_share_risk.get("min_listing_days"), 60.0)
    min_amount = to_float(a_share_risk.get("min_amount"), 300000000.0)
    min_turnover_rate = to_float(a_share_risk.get("min_turnover_rate"), 0.015)
    drawdown_enabled = to_bool(drawdown_rule.get("enabled"), True)
    drawdown_block_pct = to_float(drawdown_rule.get("block_build_add_pct"), 0.10)
    cap_multiplier = to_float(drawdown_rule.get("cap_multiplier"), 0.70)

    effective_single_stock_cap = single_stock_cap
    current_drawdown = to_float(account.get("portfolio_drawdown_pct"))
    build_blocked = False
    effective_risk_mode = risk_mode
    if drawdown_enabled and current_drawdown >= drawdown_block_pct:
        effective_single_stock_cap = single_stock_cap * cap_multiplier
        build_blocked = True
        effective_risk_mode = "DRAWDOWN_GUARD"

    action_priority = {"EXIT": 0, "REDUCE": 1, "HOLD": 2, "ADD": 3, "BUILD": 4}
    ordered_candidates = sorted(stage_input.orders_candidate, key=lambda row: action_priority.get(str(row.get("action", "")), 99))

    trade_plan: list[TradePlanRow] = []
    risk_events: list[RiskEventRow] = []
    portfolio_weight_used = 0.0
    sector_weight_used: dict[str, float] = {}
    board_weight_used: dict[str, float] = {}

    for candidate in ordered_candidates:
        action = str(candidate.get("action", "HOLD")).upper()
        symbol = str(candidate.get("symbol", ""))
        sector = str(candidate.get("sector", "UNKNOWN"))
        current_position = positions_by_symbol.get(symbol, {})
        candidate_market_view = tech_candidates_by_symbol.get(symbol, current_position)
        current_weight = to_float(current_position.get("current_weight"))
        target_weight = to_float(candidate.get("target_weight"))
        board = str(candidate.get("board") or current_position.get("board") or candidate_market_view.get("board") or board_exposure_key(symbol))
        board_cap = to_float(board_caps_config.get(board.lower(), board_caps_config.get(board, portfolio_cap)), portfolio_cap)
        is_st = to_bool(candidate_market_view.get("is_st"), to_bool(current_position.get("is_st")))
        suspended = to_bool(candidate_market_view.get("suspended"), to_bool(current_position.get("suspended")))
        list_days = to_float(candidate_market_view.get("list_days"), to_float(current_position.get("list_days"), 9999))
        amount = to_float(candidate_market_view.get("amount"))
        turnover_rate = to_float(candidate_market_view.get("turnover_rate"))
        last_price = to_float(candidate_market_view.get("last_price"), to_float(current_position.get("last_price")))
        upper_limit = to_float(candidate_market_view.get("upper_limit"), 0.0) or None
        lower_limit = to_float(candidate_market_view.get("lower_limit"), 0.0) or None
        available_quantity = to_float(current_position.get("available_quantity"), to_float(current_position.get("quantity")))
        near_limit_up = bool(candidate_market_view.get("near_upper_limit")) or is_limit_up(last_price, upper_limit, 0.015)
        near_limit_down = is_limit_down(last_price, lower_limit, 0.015)

        status = "ACCEPTED"
        w_final = target_weight
        reasons: list[str] = []

        if action in SELL_LIKE_ACTIONS or action == "HOLD":
            if action in SELL_LIKE_ACTIONS and suspended:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("suspended_security")
            elif action in SELL_LIKE_ACTIONS and t_plus_one_enabled and to_bool(current_position.get("t_plus_one_locked")):
                status = "REJECTED"
                w_final = current_weight
                reasons.append("t_plus_one_locked")
            elif action in SELL_LIKE_ACTIONS and available_quantity <= 0:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("no_available_quantity")
            elif action == "EXIT":
                w_final = 0.0
            elif action == "REDUCE":
                w_final = min(target_weight, current_weight)
            else:
                w_final = current_weight if target_weight <= 0 else min(target_weight, effective_single_stock_cap)

            if action in SELL_LIKE_ACTIONS and near_limit_down:
                reasons.append("limit_down_execution_risk")

            portfolio_weight_used += w_final
            sector_weight_used[sector] = sector_weight_used.get(sector, 0.0) + w_final
            board_weight_used[board] = board_weight_used.get(board, 0.0) + w_final
        elif action in BUY_LIKE_ACTIONS:
            desired_weight = min(target_weight, effective_single_stock_cap)
            if build_blocked:
                status = "REJECTED"
                w_final = 0.0
                reasons.append("drawdown_guard_blocks_build_add")
            elif buy_reject_if_suspended and suspended:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("suspended_security")
            elif buy_reject_if_st and is_st:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("risk_warning_security")
            elif list_days < min_listing_days:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("listing_days_too_short")
            elif amount < min_amount:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("turnover_amount_too_low")
            elif turnover_rate < min_turnover_rate:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("turnover_rate_too_low")
            elif buy_reject_if_limit_up and near_limit_up:
                status = "REJECTED"
                w_final = current_weight
                reasons.append("near_limit_up")
            else:
                portfolio_cap_left = max(portfolio_cap - portfolio_weight_used, 0.0)
                industry_cap_left = max(industry_cap - sector_weight_used.get(sector, 0.0), 0.0)
                board_cap_left = max(board_cap - board_weight_used.get(board, 0.0), 0.0)
                liquidity_score = to_float(tech_candidates_by_symbol.get(symbol, {}).get("liquidity_score"), 0.60)
                liquidity_cap = min(liquidity_cap_default, max(0.03, liquidity_score * 0.18))
                desired_increment = max(desired_weight - current_weight, 0.0)
                increment = min(desired_increment, portfolio_cap_left, industry_cap_left, board_cap_left, liquidity_cap)
                w_final = current_weight + increment

                if increment <= 0.0:
                    status = "REJECTED"
                    w_final = current_weight
                    reasons.append("no_remaining_risk_budget")
                else:
                    if increment < desired_increment:
                        reasons.append("cap_trimmed")
                    portfolio_weight_used += increment
                    sector_weight_used[sector] = sector_weight_used.get(sector, 0.0) + increment
                    board_weight_used[board] = board_weight_used.get(board, 0.0) + increment
        else:
            status = "REJECTED"
            w_final = 0.0
            reasons.append("unknown_action")

        plan_row = TradePlanRow(
            trade_date=ctx.trade_date,
            order_id=str(candidate.get("order_id", "")),
            symbol=symbol,
            name=str(candidate.get("name", "")),
            sector=sector,
            board=board,
            action=action,
            w_ai=to_float(candidate.get("w_ai")),
            w_candidate=to_float(candidate.get("w_candidate")),
            target_weight=target_weight,
            w_final=w_final,
            status=status,
            cap_hit_reason="|".join(reasons),
            risk_mode=effective_risk_mode,
            entry_price_final=to_float(candidate.get("entry_price")),
            stop_loss_price_final=to_float(candidate.get("stop_loss_price")),
            take_profit_price_final=to_float(candidate.get("take_profit_price")),
            reduce_price_final=to_float(candidate.get("reduce_price")),
            exit_price_final=to_float(candidate.get("exit_price")),
            reason=str(candidate.get("reason", "")),
        )
        trade_plan.append(plan_row)

        if status == "REJECTED" or reasons:
            risk_events.append(
                RiskEventRow(
                    order_id=plan_row.order_id,
                    symbol=symbol,
                    action=action,
                    status=status,
                    reason=plan_row.cap_hit_reason or "accepted",
                )
            )

    return trade_plan, risk_events


def _fallback_trade_plan(
    ctx: Any,
    orders_candidate: list[dict[str, Any]],
    error_message: str,
) -> tuple[list[TradePlanRow], list[RiskEventRow]]:
    trade_plan: list[TradePlanRow] = []
    risk_events: list[RiskEventRow] = []

    for candidate in orders_candidate:
        action = str(candidate.get("action", "HOLD")).upper()
        accepted = action in SELL_LIKE_ACTIONS or action == "HOLD"
        row = TradePlanRow(
            trade_date=ctx.trade_date,
            order_id=str(candidate.get("order_id", "")),
            symbol=str(candidate.get("symbol", "")),
            name=str(candidate.get("name", "")),
            sector=str(candidate.get("sector", "UNKNOWN")),
            board=str(candidate.get("board", "UNKNOWN")),
            action=action,
            w_ai=to_float(candidate.get("w_ai")),
            w_candidate=to_float(candidate.get("w_candidate")),
            target_weight=to_float(candidate.get("target_weight")),
            w_final=to_float(candidate.get("target_weight")) if accepted and action != "EXIT" else 0.0,
            status="ACCEPTED" if accepted else "REJECTED",
            cap_hit_reason="" if accepted else f"risk_guard_fallback:{error_message}",
            risk_mode="RISK_GUARD_FALLBACK",
            entry_price_final=to_float(candidate.get("entry_price")),
            stop_loss_price_final=to_float(candidate.get("stop_loss_price")),
            take_profit_price_final=to_float(candidate.get("take_profit_price")),
            reduce_price_final=to_float(candidate.get("reduce_price")),
            exit_price_final=to_float(candidate.get("exit_price")),
            reason=str(candidate.get("reason", "")),
        )
        trade_plan.append(row)
        if not accepted:
            risk_events.append(
                RiskEventRow(
                    order_id=row.order_id,
                    symbol=row.symbol,
                    action=row.action,
                    status=row.status,
                    reason=row.cap_hit_reason,
                )
            )

    return trade_plan, risk_events
