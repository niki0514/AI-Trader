from __future__ import annotations

import math
from typing import Any

from app.utils import to_bool, to_float, to_int


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def infer_exchange(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if normalized.endswith(".SH"):
        return "SSE"
    if normalized.endswith(".SZ"):
        return "SZSE"
    if normalized.endswith(".BJ"):
        return "BSE"
    return "UNKNOWN"


def infer_board(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0]

    if normalized.endswith(".BJ"):
        return "BSE"
    if normalized.endswith(".SH"):
        if code.startswith("688"):
            return "STAR"
        return "MAIN"
    if normalized.endswith(".SZ"):
        if code.startswith(("300", "301")):
            return "CHINEXT"
        return "MAIN"
    return "UNKNOWN"


def enrich_security_info(raw: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    symbol = normalize_symbol(raw.get("symbol"))
    board = infer_board(symbol)
    exchange = infer_exchange(symbol)
    name = str(raw.get("name", ""))
    last_price = to_float(raw.get("last_price"))
    prev_close = to_float(raw.get("prev_close"), to_float(raw.get("previous_close"), last_price))
    is_st = _infer_is_st(raw, name)
    list_days = to_int(raw.get("list_days"), 9999)

    upper_limit, lower_limit = compute_price_limits(
        prev_close=prev_close,
        symbol=symbol,
        is_st=is_st,
        list_days=list_days,
        config=config,
        explicit_upper=raw.get("upper_limit"),
        explicit_lower=raw.get("lower_limit"),
    )

    amount = to_float(raw.get("amount"), to_float(raw.get("turnover_amount")))
    turnover_rate = to_float(raw.get("turnover_rate"))
    relative_volume = to_float(raw.get("relative_volume"), to_float(raw.get("volume_ratio"), 1.0))
    available_quantity = to_float(raw.get("available_quantity"), to_float(raw.get("quantity")))

    return {
        "symbol": symbol,
        "name": name,
        "exchange": exchange,
        "board": board,
        "industry": str(raw.get("industry") or raw.get("sector") or "UNKNOWN"),
        "last_price": last_price,
        "prev_close": prev_close,
        "upper_limit": upper_limit,
        "lower_limit": lower_limit,
        "is_st": is_st,
        "suspended": to_bool(raw.get("suspended")),
        "list_days": list_days,
        "amount": amount,
        "turnover_rate": turnover_rate,
        "relative_volume": relative_volume,
        "available_quantity": available_quantity,
        "northbound_net_flow": to_float(raw.get("northbound_net_flow")),
    }


def default_price_limit_pct(
    symbol: str,
    *,
    is_st: bool = False,
    list_days: int = 9999,
    config: dict[str, Any] | None = None,
) -> float | None:
    board = infer_board(symbol)
    a_share_config = (config or {}).get("a_share", {})
    board_config = a_share_config.get("boards", {})

    unlimited_days = to_int(board_config.get("new_listing_unlimited_days", {}).get(board.lower()), 0)
    if list_days > 0 and list_days <= unlimited_days:
        return None

    if is_st and board == "MAIN":
        return to_float(board_config.get("main_risk_warning_price_limit_pct"), 0.05)
    if board == "CHINEXT":
        return to_float(board_config.get("chinext_price_limit_pct"), 0.20)
    if board == "STAR":
        return to_float(board_config.get("star_price_limit_pct"), 0.20)
    if board == "BSE":
        return to_float(board_config.get("bse_price_limit_pct"), 0.30)
    return to_float(board_config.get("main_price_limit_pct"), 0.10)


def compute_price_limits(
    *,
    prev_close: float,
    symbol: str,
    is_st: bool,
    list_days: int,
    config: dict[str, Any] | None = None,
    explicit_upper: Any = None,
    explicit_lower: Any = None,
) -> tuple[float | None, float | None]:
    upper_limit = to_float(explicit_upper, math.nan)
    lower_limit = to_float(explicit_lower, math.nan)
    if math.isfinite(upper_limit) and math.isfinite(lower_limit):
        return upper_limit, lower_limit

    if prev_close <= 0:
        return None, None

    limit_pct = default_price_limit_pct(
        symbol,
        is_st=is_st,
        list_days=list_days,
        config=config,
    )
    if limit_pct is None:
        return None, None

    tick = to_float((config or {}).get("a_share", {}).get("trading", {}).get("price_tick"), 0.01)
    upper = _round_to_tick(prev_close * (1.0 + limit_pct), tick)
    lower = _round_to_tick(prev_close * (1.0 - limit_pct), tick)
    return upper, lower


def lot_size_for_symbol(symbol: str, config: dict[str, Any] | None = None) -> int:
    board = infer_board(symbol)
    a_share_config = (config or {}).get("a_share", {})
    board_lots = a_share_config.get("trading", {}).get("lot_size_by_board", {})
    default_lot = to_int(a_share_config.get("trading", {}).get("default_lot_size"), 100)
    configured = to_int(board_lots.get(board.lower()), default_lot)
    return configured if configured > 0 else 100


def round_buy_quantity(quantity: float, lot_size: int) -> float:
    if quantity <= 0 or lot_size <= 0:
        return 0.0
    lots = int(quantity // lot_size)
    return float(lots * lot_size)


def round_sell_quantity(
    desired_quantity: float,
    current_quantity: float,
    lot_size: int,
    sell_all_threshold: float = 0.70,
) -> float:
    if desired_quantity <= 0 or current_quantity <= 0:
        return 0.0
    if desired_quantity >= current_quantity:
        return current_quantity
    if lot_size <= 0:
        return min(desired_quantity, current_quantity)
    if current_quantity <= lot_size:
        return current_quantity if desired_quantity / current_quantity >= sell_all_threshold else 0.0

    rounded_quantity = float(int(desired_quantity // lot_size) * lot_size)
    if rounded_quantity <= 0:
        return 0.0

    remaining_quantity = current_quantity - rounded_quantity
    odd_lot = current_quantity % lot_size
    if remaining_quantity > 0 and remaining_quantity < lot_size and odd_lot > 0:
        return rounded_quantity
    return min(rounded_quantity, current_quantity)


def estimate_fees(side: str, amount: float, symbol: str, config: dict[str, Any]) -> dict[str, float]:
    fees_config = config.get("a_share", {}).get("fees", {})
    commission_rate = to_float(fees_config.get("commission_rate"), 0.0003)
    min_commission = to_float(fees_config.get("min_commission"), 5.0)
    stamp_duty_rate_sell = to_float(fees_config.get("stamp_duty_rate_sell"), 0.0005)
    transfer_fee_rate = to_float(fees_config.get("transfer_fee_rate"), 0.00001)

    commission = max(amount * commission_rate, min_commission) if amount > 0 else 0.0
    stamp_duty = amount * stamp_duty_rate_sell if amount > 0 and side.upper() == "SELL" else 0.0
    transfer_fee = amount * transfer_fee_rate if amount > 0 and infer_exchange(symbol) in {"SSE", "SZSE", "BSE"} else 0.0
    total_fee = commission + stamp_duty + transfer_fee

    return {
        "commission": commission,
        "stamp_duty": stamp_duty,
        "transfer_fee": transfer_fee,
        "total_fee": total_fee,
    }


def is_limit_up(price: float, upper_limit: float | None, tolerance: float = 0.0005) -> bool:
    if price <= 0 or upper_limit is None or upper_limit <= 0:
        return False
    return price >= upper_limit * (1.0 - tolerance)


def is_limit_down(price: float, lower_limit: float | None, tolerance: float = 0.0005) -> bool:
    if price <= 0 or lower_limit is None or lower_limit <= 0:
        return False
    return price <= lower_limit * (1.0 + tolerance)


def board_exposure_key(symbol: str) -> str:
    return infer_board(symbol)


def _infer_is_st(raw: dict[str, Any], name: str) -> bool:
    if to_bool(raw.get("is_st")):
        return True
    normalized_name = name.strip().upper().replace("＊", "*")
    return normalized_name.startswith(("ST", "*ST", "S*ST"))


def _round_to_tick(price: float, tick: float) -> float:
    if price <= 0 or tick <= 0:
        return 0.0
    scaled = round(price / tick)
    return round(scaled * tick, 4)
