from __future__ import annotations

import math
import statistics
from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    if value in {"", None}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    if value in {"", None}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {"", None}:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) <= 1e-12:
        return default
    return numerator / denominator


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def join_tags(values: list[str]) -> str:
    return "|".join(item for item in values if item)


def index_by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_key = str(row.get(key, "")).strip()
        if row_key:
            indexed[row_key] = row
    return indexed


def make_order_id(trade_date: str, symbol: str, action: str, index: int) -> str:
    normalized_date = trade_date.replace("-", "")
    normalized_symbol = (
        symbol.replace(".", "")
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
    )
    return f"{normalized_date}-{normalized_symbol}-{action.lower()}-{index:03d}"


def as_text(value: Any) -> str:
    return "" if value is None else str(value)


def compute_sharpe_ratio(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    volatility = statistics.pstdev(daily_returns)
    if volatility <= 1e-12:
        return 0.0
    return statistics.mean(daily_returns) / volatility * math.sqrt(252)


def compute_max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = safe_div(peak - equity, peak)
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def resolve_risk_mode(snapshot: dict[str, Any], config: dict[str, Any]) -> str:
    market = snapshot.get("market", {})
    mode = str(market.get("regime") or config.get("risk", {}).get("default_mode", "NEUTRAL"))
    normalized = mode.strip().upper().replace("-", "_")
    if normalized not in {"RISK_ON", "NEUTRAL", "RISK_OFF"}:
        return "NEUTRAL"
    return normalized

