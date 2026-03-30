from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.a_share import estimate_fees, infer_board, lot_size_for_symbol, normalize_symbol
from app.adapters import read_json, write_json
from app.api.requests import OperationEntryRequest
from app.utils import make_order_id, to_float

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BUY_LIKE_ACTIONS = {"BUY", "BUILD", "ADD"}
SELL_LIKE_ACTIONS = {"SELL", "REDUCE", "EXIT"}


@dataclass(frozen=True)
class OperationValidationResult:
    valid: bool
    trade_date: str
    symbol: str
    input_action: str
    normalized_action: str
    market_action: str
    quantity: float
    price: float
    amount: float
    lot_size: int
    position_found: bool
    position: dict[str, Any] | None
    estimated_fees: dict[str, float]
    before_quantity: float
    before_available_quantity: float
    after_quantity: float
    after_available_quantity: float
    errors: list[str]
    warnings: list[str]


def validate_operation_entry(
    request: OperationEntryRequest,
    *,
    config: dict[str, Any],
    position: dict[str, Any] | None,
) -> OperationValidationResult:
    trade_date = str(request.trade_date or "").strip()
    symbol = normalize_symbol(request.symbol)
    input_action = str(request.action or "").strip().upper()
    quantity = float(request.quantity)
    price = float(request.price)
    amount = quantity * price
    lot_size = lot_size_for_symbol(symbol, config)
    current_position = dict(position) if position else None
    current_qty = to_float((current_position or {}).get("quantity"))
    current_available_qty = to_float((current_position or {}).get("available_quantity"), current_qty)

    errors: list[str] = []
    warnings: list[str] = []

    if not DATE_RE.fullmatch(trade_date):
        errors.append(f"invalid trade_date: {trade_date}")
    if not symbol:
        errors.append("symbol is required")

    market_action = ""
    if input_action in BUY_LIKE_ACTIONS:
        market_action = "BUY"
    elif input_action in SELL_LIKE_ACTIONS:
        market_action = "SELL"
    else:
        errors.append("action must be one of BUY, SELL, BUILD, ADD, REDUCE, EXIT")

    if quantity <= 0:
        errors.append("quantity must be > 0")
    if price <= 0:
        errors.append("price must be > 0")

    normalized_action = ""
    if market_action == "BUY":
        if input_action == "BUILD" and current_qty > 0:
            errors.append("BUILD requires no existing position")
        if input_action == "ADD" and current_qty <= 0:
            errors.append("ADD requires an existing position")
        normalized_action = input_action if input_action in {"BUILD", "ADD"} else ("ADD" if current_qty > 0 else "BUILD")
    elif market_action == "SELL":
        if current_qty <= 0:
            errors.append(f"no existing position found for symbol={symbol}")
        if current_available_qty <= 0:
            errors.append(f"no sellable quantity available for symbol={symbol}")
        if quantity > current_available_qty + 1e-8:
            errors.append(
                f"quantity exceeds available_quantity: requested={quantity:g}, available={current_available_qty:g}"
            )
        if input_action == "REDUCE" and current_qty > 0 and quantity >= current_qty - 1e-8:
            errors.append("REDUCE quantity must be less than current position quantity")
        if input_action == "EXIT" and current_qty > 0 and abs(quantity - current_qty) > 1e-8:
            errors.append("EXIT quantity must equal current position quantity")
        normalized_action = input_action if input_action in {"REDUCE", "EXIT"} else (
            "EXIT" if current_qty > 0 and abs(quantity - current_qty) <= 1e-8 else "REDUCE"
        )

    if quantity > 0 and lot_size > 1 and not _is_valid_lot_quantity(
        quantity,
        lot_size=lot_size,
        market_action=market_action,
        available_quantity=current_available_qty,
    ):
        errors.append(f"quantity must align with lot_size={lot_size}")

    last_price = to_float((current_position or {}).get("last_price"))
    if last_price > 0:
        deviation = abs(price - last_price) / last_price
        if deviation >= 0.10:
            warnings.append(f"price deviates materially from last_price={last_price:g}")

    upper_limit = to_float((current_position or {}).get("upper_limit"))
    lower_limit = to_float((current_position or {}).get("lower_limit"))
    if upper_limit > 0 and price > upper_limit + 1e-8:
        errors.append(f"price exceeds upper_limit={upper_limit:g}")
    if lower_limit > 0 and price < lower_limit - 1e-8:
        errors.append(f"price is below lower_limit={lower_limit:g}")

    after_quantity = current_qty
    after_available_quantity = current_available_qty
    if market_action == "BUY":
        after_quantity = current_qty + quantity
    elif market_action == "SELL":
        after_quantity = max(current_qty - quantity, 0.0)
        after_available_quantity = max(min(current_available_qty, current_qty) - quantity, 0.0)

    estimated_fees = estimate_fees(market_action or "BUY", amount, symbol, config) if symbol else {}

    return OperationValidationResult(
        valid=not errors,
        trade_date=trade_date,
        symbol=symbol,
        input_action=input_action,
        normalized_action=normalized_action,
        market_action=market_action,
        quantity=quantity,
        price=price,
        amount=amount,
        lot_size=lot_size,
        position_found=current_qty > 0,
        position=dict(current_position) if current_position else None,
        estimated_fees=estimated_fees,
        before_quantity=current_qty,
        before_available_quantity=current_available_qty,
        after_quantity=after_quantity,
        after_available_quantity=after_available_quantity,
        errors=errors,
        warnings=warnings,
    )


def operation_ledger_path(output_root: Path, trade_date: str) -> Path:
    return output_root / "manual_operations" / f"{trade_date}.json"


def load_operation_entries(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    payload = read_json(ledger_path)
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return []
    return [dict(item) for item in raw_entries if isinstance(item, dict)]


def append_operation_entry(ledger_path: Path, *, trade_date: str, entry: dict[str, Any]) -> None:
    entries = load_operation_entries(ledger_path)
    entries.append(dict(entry))
    write_json(
        ledger_path,
        {
            "trade_date": trade_date,
            "entry_count": len(entries),
            "entries": entries,
        },
    )


def build_effective_position(
    *,
    base_position: dict[str, Any] | None,
    symbol: str,
    trade_date: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current = dict(base_position) if base_position else None
    normalized_symbol = normalize_symbol(symbol)
    for entry in entries:
        if normalize_symbol(entry.get("symbol")) != normalized_symbol:
            continue
        current = _apply_operation_entry(current, trade_date=trade_date, symbol=normalized_symbol, entry=entry)
    return current


def build_submitted_operation(
    *,
    result: OperationValidationResult,
    request: OperationEntryRequest,
    sequence: int,
    submitted_at: str,
) -> dict[str, Any]:
    operation_id = make_order_id(result.trade_date, result.symbol, result.normalized_action or result.input_action, sequence)
    occurred_at = request.occurred_at or submitted_at
    return {
        "operation_id": operation_id,
        "submitted_at": submitted_at,
        "occurred_at": occurred_at,
        "trade_date": result.trade_date,
        "symbol": result.symbol,
        "input_action": result.input_action,
        "normalized_action": result.normalized_action,
        "market_action": result.market_action,
        "quantity": result.quantity,
        "price": result.price,
        "amount": result.amount,
        "estimated_fees": dict(result.estimated_fees),
        "before_quantity": result.before_quantity,
        "before_available_quantity": result.before_available_quantity,
        "after_quantity": result.after_quantity,
        "after_available_quantity": result.after_available_quantity,
        "note": request.note,
        "operator": request.operator,
        "source": request.source,
        "warnings": list(result.warnings),
    }


def _apply_operation_entry(
    current_position: dict[str, Any] | None,
    *,
    trade_date: str,
    symbol: str,
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    current = dict(current_position) if current_position else _new_position_shell(symbol=symbol, trade_date=trade_date)
    normalized_action = str(entry.get("normalized_action") or entry.get("input_action") or "").strip().upper()
    quantity = to_float(entry.get("quantity"))
    price = to_float(entry.get("price"))
    current_qty = to_float(current.get("quantity"))
    current_available_qty = to_float(current.get("available_quantity"), current_qty)

    if normalized_action in {"BUILD", "ADD"}:
        new_qty = current_qty + quantity
        old_cost = to_float(current.get("avg_cost"))
        new_avg_cost = ((current_qty * old_cost) + (quantity * price)) / new_qty if new_qty > 0 else price
        current.update(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "board": str(current.get("board") or infer_board(symbol)),
                "quantity": new_qty,
                "available_quantity": current_available_qty,
                "avg_cost": new_avg_cost,
                "last_price": price,
                "market_value": new_qty * price,
                "last_trade_date": trade_date,
            }
        )
        return current

    if normalized_action in {"REDUCE", "EXIT"}:
        remaining_qty = max(current_qty - quantity, 0.0)
        remaining_available_qty = max(min(current_available_qty, current_qty) - quantity, 0.0)
        if remaining_qty <= 1e-8:
            return None
        current.update(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "quantity": remaining_qty,
                "available_quantity": min(remaining_qty, remaining_available_qty),
                "last_price": price,
                "market_value": remaining_qty * price,
                "last_trade_date": trade_date,
            }
        )
        return current

    return current_position


def _new_position_shell(*, symbol: str, trade_date: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "name": "",
        "sector": "UNKNOWN",
        "board": infer_board(symbol),
        "quantity": 0.0,
        "available_quantity": 0.0,
        "avg_cost": 0.0,
        "prev_close": 0.0,
        "last_price": 0.0,
        "upper_limit": 0.0,
        "lower_limit": 0.0,
        "market_value": 0.0,
        "weight": 0.0,
        "unrealized_pnl_pct": 0.0,
        "is_st": False,
        "suspended": False,
        "last_trade_date": trade_date,
    }


def _is_valid_lot_quantity(
    quantity: float,
    *,
    lot_size: int,
    market_action: str,
    available_quantity: float,
) -> bool:
    if lot_size <= 1:
        return True
    multiples = round(quantity / float(lot_size))
    if abs(quantity - (multiples * float(lot_size))) <= 1e-8:
        return True
    return market_action == "SELL" and abs(quantity - available_quantity) <= 1e-8

