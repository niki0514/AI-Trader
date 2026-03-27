from __future__ import annotations

from typing import Any

from app.a_share import (
    enrich_security_info,
    estimate_fees,
    is_limit_down,
    is_limit_up,
    lot_size_for_symbol,
    round_buy_quantity,
    round_sell_quantity,
)
from app.contracts import BUY_LIKE_ACTIONS, SELL_LIKE_ACTIONS
from app.pipeline.io import ExecutorStageInput
from app.pipeline.outputs import ExecutorStageOutput, NavRow, PositionRow, SimFillRow
from app.pipeline.results import StageResult
from app.utils import compute_max_drawdown, index_by, safe_div, to_bool, to_float


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    stage_input = ExecutorStageInput.from_payload(payload)
    trade_plan = list(stage_input.trade_plan)
    try:
        sim_fill, positions, nav = _execute_trade_plan(ctx, stage_input)
        executor_failed = False
        stage_label = "simulated_execution_cn_a_share"
    except Exception as exc:
        sim_fill, positions, nav = _fallback_execution(ctx, stage_input, str(exc))
        executor_failed = True
        stage_label = "executor_fallback"

    filled_order_count = len([row for row in sim_fill if row.status == "FILLED"])
    total_fees = sum(row.total_fee for row in sim_fill)
    return StageResult(
        updates=ExecutorStageOutput(
            sim_fill=sim_fill,
            positions=positions,
            nav=nav,
            executor_failed=executor_failed,
        ),
        stage_note=f"{stage_label}; filled_orders={filled_order_count}; fees={total_fees:.2f}",
    )


def _execute_trade_plan(
    ctx: Any,
    stage_input: ExecutorStageInput,
) -> tuple[list[SimFillRow], list[PositionRow], list[NavRow]]:
    trade_plan = list(stage_input.trade_plan)
    account = dict(stage_input.portfolio.account)
    positions_prev = [dict(item) for item in stage_input.portfolio.positions_prev]
    positions_by_symbol = index_by(positions_prev, "symbol")
    base_watchlist = list(stage_input.execution_watchlist)
    watchlist_by_symbol = {
        str(item.get("symbol", "")).strip().upper(): {**dict(item), **enrich_security_info(item, ctx.config)}
        for item in base_watchlist
    }

    cash = to_float(account.get("cash"))
    starting_equity = to_float(account.get("total_equity"))
    prev_total_equity = to_float(account.get("prev_total_equity"), starting_equity)
    initial_equity = to_float(account.get("initial_equity"), prev_total_equity or starting_equity)

    execution_config = ctx.config.get("execution", {})
    slippage_bps = to_float(execution_config.get("slippage_bps"), 8.0)
    allow_fractional = to_bool(execution_config.get("allow_fractional_shares"), False)
    disable_executor = to_bool(ctx.config.get("degrade", {}).get("disable_executor"), False)

    sim_fill: list[SimFillRow] = []
    trading_fees = 0.0

    for plan_row in trade_plan:
        symbol = str(plan_row.get("symbol", "")).strip().upper()
        action = str(plan_row.get("action", "HOLD")).upper()
        current_position = positions_by_symbol.get(symbol, {})
        market_view = _market_view(symbol, current_position, watchlist_by_symbol, ctx.config)
        board = str(plan_row.get("board") or market_view.get("board") or current_position.get("board") or "UNKNOWN")

        status = "SKIPPED"
        planned_price = _planned_price(plan_row, current_position)
        market_price = _market_price(current_position, market_view)
        fill_price = planned_price
        quantity = 0.0
        filled_amount = 0.0
        fees = _empty_fees()
        note = str(plan_row.get("cap_hit_reason") or plan_row.get("reason") or "")
        upper_limit = to_float(market_view.get("upper_limit"), 0.0) or None
        lower_limit = to_float(market_view.get("lower_limit"), 0.0) or None
        suspended = to_bool(market_view.get("suspended"), to_bool(current_position.get("suspended")))

        if str(plan_row.get("status", "REJECTED")).upper() != "ACCEPTED":
            note = note or "risk_rejected"
        elif disable_executor:
            note = "executor_disabled"
        elif action == "HOLD":
            note = "hold_no_execution"
        elif suspended:
            note = "suspended_no_execution"
        elif action in BUY_LIKE_ACTIONS:
            execution_base_price = _buy_execution_price(planned_price, market_price)
            fill_price = execution_base_price * (1.0 + slippage_bps / 10000.0)
            if upper_limit is not None:
                fill_price = min(fill_price, upper_limit)

            if is_limit_up(market_price or fill_price, upper_limit, 0.015):
                note = "limit_up_no_fill"
            else:
                target_qty = _target_buy_quantity(
                    symbol=symbol,
                    action=action,
                    current_position=current_position,
                    total_equity=starting_equity,
                    target_weight=to_float(plan_row.get("w_final")),
                    price=fill_price,
                    allow_fractional=allow_fractional,
                    config=ctx.config,
                )
                quantity = _affordable_buy_quantity(
                    symbol=symbol,
                    desired_quantity=target_qty,
                    cash=cash,
                    price=fill_price,
                    allow_fractional=allow_fractional,
                    config=ctx.config,
                )
                if quantity > 0:
                    filled_amount = quantity * fill_price
                    fees = estimate_fees("BUY", filled_amount, symbol, ctx.config)
                    total_cost = filled_amount + fees["total_fee"]
                    if total_cost <= cash + 1e-8:
                        status = "FILLED"
                        note = "add_filled" if action == "ADD" else "build_filled"
                        cash -= total_cost
                        trading_fees += fees["total_fee"]
                        _apply_buy_fill(
                            positions_by_symbol=positions_by_symbol,
                            plan_row=plan_row,
                            market_view=market_view,
                            quantity=quantity,
                            fill_price=fill_price,
                            trade_date=ctx.trade_date,
                            total_cost=total_cost,
                        )
                    else:
                        note = "insufficient_cash_after_fees"
                else:
                    note = "no_affordable_round_lot"
        elif action in SELL_LIKE_ACTIONS:
            execution_base_price = _sell_execution_price(planned_price, market_price)
            fill_price = execution_base_price * (1.0 - slippage_bps / 10000.0)
            if lower_limit is not None:
                fill_price = max(fill_price, lower_limit)

            if is_limit_down(market_price or fill_price, lower_limit, 0.015):
                note = "limit_down_no_liquidity"
            else:
                quantity = _sell_quantity(
                    symbol=symbol,
                    action=action,
                    plan_row=plan_row,
                    current_position=current_position,
                    total_equity=starting_equity,
                    price=fill_price,
                    allow_fractional=allow_fractional,
                    config=ctx.config,
                )
                if quantity > 0:
                    filled_amount = quantity * fill_price
                    fees = estimate_fees("SELL", filled_amount, symbol, ctx.config)
                    net_proceeds = filled_amount - fees["total_fee"]
                    status = "FILLED"
                    note = "sell_filled"
                    cash += net_proceeds
                    trading_fees += fees["total_fee"]
                    _apply_sell_fill(
                        positions_by_symbol=positions_by_symbol,
                        plan_row=plan_row,
                        market_view=market_view,
                        quantity=quantity,
                        fill_price=fill_price,
                        trade_date=ctx.trade_date,
                    )
                else:
                    note = "no_sellable_round_lot"
        else:
            note = "unknown_action"

        sim_fill.append(
            SimFillRow(
                trade_date=ctx.trade_date,
                order_id=str(plan_row.get("order_id", "")),
                symbol=symbol,
                name=str(plan_row.get("name", "")),
                board=board,
                action=action,
                planned_price=planned_price,
                fill_price=fill_price if status == "FILLED" else 0.0,
                price_deviation_bps=_price_deviation_bps(planned_price, fill_price) if status == "FILLED" else 0.0,
                quantity=quantity,
                filled_amount=filled_amount,
                commission=fees["commission"],
                stamp_duty=fees["stamp_duty"],
                transfer_fee=fees["transfer_fee"],
                total_fee=fees["total_fee"],
                status=status,
                note=note,
            )
        )

    positions = _finalize_positions(
        trade_date=ctx.trade_date,
        positions_by_symbol=positions_by_symbol,
        watchlist_by_symbol=watchlist_by_symbol,
        cash=cash,
        initial_equity=initial_equity,
        prev_total_equity=prev_total_equity,
    )
    market_value = sum(position.market_value for position in positions)
    total_equity = cash + market_value
    equity_curve = [initial_equity or total_equity, prev_total_equity or total_equity, total_equity]
    nav = [
        NavRow(
            trade_date=ctx.trade_date,
            cash=cash,
            market_value=market_value,
            total_equity=total_equity,
            trading_fees=trading_fees,
            daily_return=safe_div(total_equity - prev_total_equity, prev_total_equity or total_equity),
            cum_return=safe_div(total_equity - initial_equity, initial_equity or total_equity),
            max_drawdown=max(
                to_float(account.get("portfolio_drawdown_pct")),
                compute_max_drawdown(equity_curve),
            ),
            filled_order_count=len([row for row in sim_fill if row.status == "FILLED"]),
        )
    ]
    return sim_fill, positions, nav


def _fallback_execution(
    ctx: Any,
    stage_input: ExecutorStageInput,
    error_message: str,
) -> tuple[list[SimFillRow], list[dict[str, Any]], list[NavRow]]:
    trade_plan = list(stage_input.trade_plan)
    positions = [dict(item) for item in stage_input.portfolio.positions_prev]
    account = dict(stage_input.portfolio.account)
    sim_fill = [
        SimFillRow(
            trade_date=ctx.trade_date,
            order_id=str(row.get("order_id", "")),
            symbol=str(row.get("symbol", "")),
            name=str(row.get("name", "")),
            board=str(row.get("board", "UNKNOWN")),
            action=str(row.get("action", "")),
            planned_price=_planned_price(row, index_by(positions, "symbol").get(str(row.get("symbol", "")), {})),
            fill_price=0.0,
            price_deviation_bps=0.0,
            quantity=0.0,
            filled_amount=0.0,
            commission=0.0,
            stamp_duty=0.0,
            transfer_fee=0.0,
            total_fee=0.0,
            status="SKIPPED",
            note=f"executor_failed:{error_message}",
        )
        for row in trade_plan
    ]

    market_value = sum(to_float(position.get("market_value")) for position in positions)
    cash = to_float(account.get("cash"))
    total_equity = cash + market_value
    nav = [
        NavRow(
            trade_date=ctx.trade_date,
            cash=cash,
            market_value=market_value,
            total_equity=total_equity,
            trading_fees=0.0,
            daily_return=0.0,
            cum_return=safe_div(
                total_equity - to_float(account.get("initial_equity"), total_equity),
                to_float(account.get("initial_equity"), total_equity),
            ),
            max_drawdown=to_float(account.get("portfolio_drawdown_pct")),
            filled_order_count=0,
        )
    ]
    return sim_fill, positions, nav


def _planned_price(plan_row: dict[str, Any], current_position: dict[str, Any]) -> float:
    action = str(plan_row.get("action", "HOLD")).upper()
    if action in BUY_LIKE_ACTIONS:
        return to_float(plan_row.get("entry_price_final"))
    if action == "REDUCE":
        return to_float(plan_row.get("reduce_price_final"))
    if action == "EXIT":
        return to_float(plan_row.get("exit_price_final"))
    return to_float(current_position.get("last_price"))


def _market_view(
    symbol: str,
    current_position: dict[str, Any],
    watchlist_by_symbol: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    if symbol in watchlist_by_symbol:
        return dict(watchlist_by_symbol[symbol])
    if current_position:
        return {**dict(current_position), **enrich_security_info(current_position, config)}
    return {}


def _market_price(current_position: dict[str, Any], market_view: dict[str, Any]) -> float:
    if current_position:
        return to_float(current_position.get("last_price"))
    return to_float(market_view.get("last_price"))


def _buy_execution_price(planned_price: float, market_price: float) -> float:
    if planned_price > 0 and market_price > 0:
        return max(planned_price, market_price)
    return planned_price or market_price


def _sell_execution_price(planned_price: float, market_price: float) -> float:
    if planned_price > 0 and market_price > 0:
        return min(planned_price, market_price)
    return planned_price or market_price


def _quantity_for_weight(total_equity: float, target_weight: float, price: float, allow_fractional: bool) -> float:
    if price <= 0 or target_weight <= 0 or total_equity <= 0:
        return 0.0
    quantity = total_equity * target_weight / price
    return quantity if allow_fractional else float(int(quantity))


def _target_buy_quantity(
    *,
    symbol: str,
    action: str,
    current_position: dict[str, Any],
    total_equity: float,
    target_weight: float,
    price: float,
    allow_fractional: bool,
    config: dict[str, Any],
) -> float:
    target_final_qty = _quantity_for_weight(total_equity, target_weight, price, allow_fractional)
    current_qty = to_float(current_position.get("quantity"))
    desired_qty = max(target_final_qty - current_qty, 0.0) if action == "ADD" else target_final_qty
    if allow_fractional:
        return desired_qty
    lot_size = lot_size_for_symbol(symbol, config)
    return round_buy_quantity(desired_qty, lot_size)


def _affordable_buy_quantity(
    *,
    symbol: str,
    desired_quantity: float,
    cash: float,
    price: float,
    allow_fractional: bool,
    config: dict[str, Any],
) -> float:
    if desired_quantity <= 0 or cash <= 0 or price <= 0:
        return 0.0

    quantity = desired_quantity
    if allow_fractional:
        affordable = cash / price
        return min(quantity, affordable)

    lot_size = lot_size_for_symbol(symbol, config)
    affordable_qty = round_buy_quantity(cash / price, lot_size)
    quantity = min(quantity, affordable_qty)

    while quantity > 0:
        amount = quantity * price
        fees = estimate_fees("BUY", amount, symbol, config)
        if amount + fees["total_fee"] <= cash + 1e-8:
            return quantity
        quantity -= float(lot_size)

    return 0.0


def _sell_quantity(
    *,
    symbol: str,
    action: str,
    plan_row: dict[str, Any],
    current_position: dict[str, Any],
    total_equity: float,
    price: float,
    allow_fractional: bool,
    config: dict[str, Any],
) -> float:
    current_qty = to_float(current_position.get("quantity"))
    available_qty = to_float(current_position.get("available_quantity"), current_qty)
    if current_qty <= 0 or available_qty <= 0:
        return 0.0
    if action == "EXIT":
        return min(available_qty, current_qty)

    target_qty = _quantity_for_weight(total_equity, to_float(plan_row.get("w_final")), price, allow_fractional)
    desired_sell_qty = max(current_qty - target_qty, 0.0)
    desired_sell_qty = min(desired_sell_qty, available_qty)
    if allow_fractional:
        return desired_sell_qty

    lot_size = lot_size_for_symbol(symbol, config)
    return round_sell_quantity(desired_sell_qty, available_qty, lot_size)


def _apply_buy_fill(
    *,
    positions_by_symbol: dict[str, dict[str, Any]],
    plan_row: dict[str, Any],
    market_view: dict[str, Any],
    quantity: float,
    fill_price: float,
    trade_date: str,
    total_cost: float,
) -> None:
    symbol = str(plan_row.get("symbol", ""))
    existing = dict(positions_by_symbol.get(symbol, {}))
    old_qty = to_float(existing.get("quantity"))
    old_cost = to_float(existing.get("avg_cost"))
    new_qty = old_qty + quantity
    gross_cost = (old_qty * old_cost) + total_cost
    new_avg_cost = safe_div(gross_cost, new_qty, fill_price) if new_qty > 0 else fill_price
    prev_close = to_float(existing.get("prev_close"), to_float(market_view.get("prev_close"), fill_price))
    upper_limit = to_float(existing.get("upper_limit"), to_float(market_view.get("upper_limit")))
    lower_limit = to_float(existing.get("lower_limit"), to_float(market_view.get("lower_limit")))

    existing.update(
        {
            "trade_date": trade_date,
            "symbol": symbol,
            "name": plan_row.get("name", market_view.get("name", "")),
            "sector": plan_row.get("sector", market_view.get("industry", "UNKNOWN")),
            "board": plan_row.get("board", market_view.get("board", "UNKNOWN")),
            "quantity": new_qty,
            "available_quantity": 0.0,
            "avg_cost": new_avg_cost,
            "prev_close": prev_close,
            "last_price": fill_price,
            "upper_limit": upper_limit,
            "lower_limit": lower_limit,
            "market_value": new_qty * fill_price,
            "is_st": to_bool(market_view.get("is_st")),
            "suspended": False,
            "last_trade_date": trade_date,
            "current_weight": 0.0,
            "unrealized_pnl_pct": safe_div(fill_price - new_avg_cost, new_avg_cost),
            "t_plus_one_locked": True,
        }
    )
    positions_by_symbol[symbol] = existing


def _apply_sell_fill(
    *,
    positions_by_symbol: dict[str, dict[str, Any]],
    plan_row: dict[str, Any],
    market_view: dict[str, Any],
    quantity: float,
    fill_price: float,
    trade_date: str,
) -> None:
    symbol = str(plan_row.get("symbol", ""))
    existing = dict(positions_by_symbol.get(symbol, {}))
    current_qty = to_float(existing.get("quantity"))
    remaining_qty = max(current_qty - quantity, 0.0)
    if remaining_qty <= 1e-8:
        positions_by_symbol.pop(symbol, None)
        return

    existing.update(
        {
            "quantity": remaining_qty,
            "available_quantity": max(remaining_qty, 0.0),
            "last_price": fill_price,
            "prev_close": to_float(existing.get("prev_close"), to_float(market_view.get("prev_close"), fill_price)),
            "upper_limit": to_float(existing.get("upper_limit"), to_float(market_view.get("upper_limit"))),
            "lower_limit": to_float(existing.get("lower_limit"), to_float(market_view.get("lower_limit"))),
            "market_value": remaining_qty * fill_price,
            "last_trade_date": trade_date,
            "t_plus_one_locked": False,
        }
    )
    positions_by_symbol[symbol] = existing


def _finalize_positions(
    *,
    trade_date: str,
    positions_by_symbol: dict[str, dict[str, Any]],
    watchlist_by_symbol: dict[str, dict[str, Any]],
    cash: float,
    initial_equity: float,
    prev_total_equity: float,
) -> list[PositionRow]:
    positions: list[PositionRow] = []
    total_market_value = sum(to_float(item.get("quantity")) * to_float(item.get("last_price")) for item in positions_by_symbol.values())
    total_equity = cash + total_market_value
    reference_equity = total_equity or prev_total_equity or initial_equity or 1.0

    for symbol, position in positions_by_symbol.items():
        market_view = watchlist_by_symbol.get(symbol, {})
        quantity = to_float(position.get("quantity"))
        last_price = to_float(position.get("last_price"), to_float(market_view.get("last_price")))
        avg_cost = to_float(position.get("avg_cost"))
        market_value = quantity * last_price
        positions.append(
            PositionRow(
                trade_date=trade_date,
                symbol=str(position.get("symbol", "")),
                name=str(position.get("name", "")),
                sector=str(position.get("sector", "UNKNOWN")),
                board=str(position.get("board", market_view.get("board", "UNKNOWN"))),
                quantity=quantity,
                available_quantity=quantity,
                avg_cost=avg_cost,
                prev_close=to_float(position.get("prev_close"), to_float(market_view.get("prev_close"), last_price)),
                last_price=last_price,
                upper_limit=to_float(position.get("upper_limit"), to_float(market_view.get("upper_limit"))),
                lower_limit=to_float(position.get("lower_limit"), to_float(market_view.get("lower_limit"))),
                market_value=market_value,
                weight=safe_div(market_value, reference_equity),
                unrealized_pnl_pct=safe_div(last_price - avg_cost, avg_cost),
                is_st=to_bool(position.get("is_st"), to_bool(market_view.get("is_st"))),
                suspended=to_bool(position.get("suspended"), to_bool(market_view.get("suspended"))),
                last_trade_date=str(position.get("last_trade_date", "")),
            )
        )

    return sorted(positions, key=lambda item: item.symbol)


def _price_deviation_bps(planned_price: float, fill_price: float) -> float:
    if planned_price <= 0:
        return 0.0
    return (fill_price - planned_price) / planned_price * 10000.0


def _empty_fees() -> dict[str, float]:
    return {
        "commission": 0.0,
        "stamp_duty": 0.0,
        "transfer_fee": 0.0,
        "total_fee": 0.0,
    }
