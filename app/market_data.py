from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import math
import os
from statistics import pstdev
from time import sleep
from typing import Any
from urllib.parse import quote_plus

from app.a_share import normalize_symbol
from app.utils import clamp, join_tags, safe_div, to_bool, to_float, to_int

try:
    from sqlalchemy import bindparam, create_engine, text
    from sqlalchemy.exc import SQLAlchemyError
except Exception:  # pragma: no cover - graceful fallback when dependency is unavailable
    bindparam = None
    create_engine = None
    text = None
    SQLAlchemyError = Exception


MYSQL_SERVER_URL = os.environ.get("MYSQL_SERVER_URL", "10.100.0.28:3306")
WIND_DB_USER = os.environ.get("WIND_DB_USER", "wind_admin")
WIND_DB_PASS = os.environ.get("WIND_DB_PASS", "ELPWN2YJRXBCQKYd")
WIND_DB_NAME = os.environ.get("WIND_DB_NAME", "winddb")
DB_WIND_URL = os.environ.get(
    "DB_WIND_URL",
    (
        "mysql+pymysql://"
        f"{quote_plus(WIND_DB_USER)}:{quote_plus(WIND_DB_PASS)}@{MYSQL_SERVER_URL}/{WIND_DB_NAME}"
        "?charset=utf8mb4"
    ),
)

WIND_QUERY_BATCH_SIZE = 4
WIND_QUERY_MAX_RETRIES = 2
WIND_QUERY_RETRY_SLEEP_SECONDS = 0.5


@dataclass(frozen=True)
class WindSettings:
    enabled: bool
    strict: bool
    lookback_days: int
    min_history_days: int
    prefer_source_prices: bool
    connect_timeout_seconds: int
    db_url: str


def enrich_snapshot_with_market_data(
    snapshot: dict[str, Any],
    config: dict[str, Any],
    trade_date: str,
) -> dict[str, Any]:
    enriched = copy.deepcopy(snapshot)
    settings = _load_wind_settings(config)
    wind_context: dict[str, Any] = {
        "provider": "wind_mysql",
        "table": "ASHAREEODPRICES",
        "status": "disabled",
        "trade_date": trade_date,
        "requested_symbols": 0,
        "resolved_symbols": 0,
        "lookback_days": settings.lookback_days,
        "min_history_days": settings.min_history_days,
    }

    if not settings.enabled:
        wind_context["message"] = "wind_market_data_disabled"
        _attach_market_context(enriched, wind_context)
        return enriched

    symbols = _collect_snapshot_symbols(enriched)
    wind_context["requested_symbols"] = len(symbols)
    if not symbols:
        wind_context["status"] = "skipped"
        wind_context["message"] = "no_symbols_to_enrich"
        _attach_market_context(enriched, wind_context)
        return enriched

    try:
        history_by_symbol = _fetch_ashare_history(
            symbols=symbols,
            trade_date=trade_date,
            lookback_days=settings.lookback_days,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            db_url=settings.db_url,
        )
        wind_context["resolved_symbols"] = len(history_by_symbol)

        positions_enriched = 0
        watchlist_enriched = 0
        for collection_name in ("positions", "watchlist"):
            enriched_rows: list[dict[str, Any]] = []
            for row in enriched.get(collection_name, []):
                raw_row = dict(row)
                symbol = normalize_symbol(raw_row.get("symbol"))
                history = history_by_symbol.get(symbol, [])
                if not history:
                    raw_row.setdefault("market_data_source", str(raw_row.get("market_data_source") or "snapshot"))
                    enriched_rows.append(raw_row)
                    continue

                market_view = _build_market_view(
                    history=history,
                    trade_date=trade_date,
                    min_history_days=settings.min_history_days,
                )
                merged = _merge_market_view(
                    raw_row=raw_row,
                    market_view=market_view,
                    prefer_source_prices=settings.prefer_source_prices,
                )
                enriched_rows.append(merged)
                if collection_name == "positions":
                    positions_enriched += 1
                else:
                    watchlist_enriched += 1
            enriched[collection_name] = enriched_rows

        wind_context["status"] = "ok" if history_by_symbol else "empty"
        wind_context["positions_enriched"] = positions_enriched
        wind_context["watchlist_enriched"] = watchlist_enriched
        wind_context["message"] = "wind_market_data_applied" if history_by_symbol else "no_matching_rows_found"
        _attach_market_context(enriched, wind_context)
        return enriched
    except Exception as exc:
        wind_context["status"] = "fallback"
        wind_context["message"] = str(exc)
        _attach_market_context(enriched, wind_context)
        if settings.strict:
            raise
        return enriched


def summarize_market_data_context(snapshot: dict[str, Any]) -> str:
    context = (snapshot.get("market_data_context") or {}).get("wind", {})
    if not isinstance(context, dict):
        return "wind_context_missing"

    status = str(context.get("status", "unknown"))
    requested = to_int(context.get("requested_symbols"))
    resolved = to_int(context.get("resolved_symbols"))
    watchlist_enriched = to_int(context.get("watchlist_enriched"))
    positions_enriched = to_int(context.get("positions_enriched"))
    return (
        f"wind={status}; symbols={resolved}/{requested}; "
        f"watchlist={watchlist_enriched}; positions={positions_enriched}"
    )


def build_market_data_lookup(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for collection_name in ("positions", "watchlist"):
        for row in snapshot.get(collection_name, []):
            symbol = normalize_symbol((row or {}).get("symbol"))
            if symbol:
                lookup[symbol] = dict(row)
    return lookup


def _load_wind_settings(config: dict[str, Any]) -> WindSettings:
    market_data_config = config.get("market_data", {})
    wind_config = market_data_config.get("wind", {})
    return WindSettings(
        enabled=to_bool(wind_config.get("enabled"), True),
        strict=to_bool(wind_config.get("strict"), True),
        lookback_days=max(to_int(wind_config.get("history_lookback_days"), 120), 30),
        min_history_days=max(to_int(wind_config.get("min_history_days"), 30), 10),
        prefer_source_prices=to_bool(wind_config.get("prefer_source_prices"), True),
        connect_timeout_seconds=max(to_int(wind_config.get("connect_timeout_seconds"), 3), 1),
        db_url=str(wind_config.get("db_url") or DB_WIND_URL),
    )


def _attach_market_context(snapshot: dict[str, Any], wind_context: dict[str, Any]) -> None:
    snapshot["market_data_context"] = {"wind": wind_context}


def _collect_snapshot_symbols(snapshot: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for collection_name in ("positions", "watchlist"):
        for row in snapshot.get(collection_name, []):
            symbol = normalize_symbol((row or {}).get("symbol"))
            if symbol:
                symbols.append(symbol)
    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    return ordered


def _fetch_ashare_history(
    *,
    symbols: list[str],
    trade_date: str,
    lookback_days: int,
    connect_timeout_seconds: int,
    db_url: str,
) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    if create_engine is None or text is None or bindparam is None:
        raise RuntimeError("sqlalchemy_not_available")

    end_trade_date = _to_db_trade_date(trade_date)
    start_trade_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback_days * 3)).strftime(
        "%Y%m%d"
    )
    query = (
        text(
            """
            SELECT
              S_INFO_WINDCODE,
              TRADE_DT,
              S_DQ_OPEN,
              S_DQ_HIGH,
              S_DQ_LOW,
              S_DQ_CLOSE,
              S_DQ_PRECLOSE,
              S_DQ_PCTCHANGE,
              S_DQ_VOLUME,
              S_DQ_AMOUNT,
              S_DQ_AVGPRICE,
              S_DQ_CHANGE,
              S_DQ_LIMIT,
              S_DQ_STOPPING
            FROM ASHAREEODPRICES
            WHERE S_INFO_WINDCODE IN :symbols
              AND TRADE_DT >= :start_trade_date
              AND TRADE_DT <= :end_trade_date
            ORDER BY S_INFO_WINDCODE, TRADE_DT
            """
        ).bindparams(bindparam("symbols", expanding=True))
    )

    history_by_symbol: dict[str, list[dict[str, Any]]] = {}
    try:
        engine = _get_wind_engine(db_url=db_url, connect_timeout_seconds=connect_timeout_seconds)
        for symbol_batch in _chunked_symbols(symbols, WIND_QUERY_BATCH_SIZE):
            rows = _execute_history_batch(
                engine=engine,
                query=query,
                symbols=symbol_batch,
                start_trade_date=start_trade_date,
                end_trade_date=end_trade_date,
            )
            for row in rows:
                symbol = normalize_symbol(row.get("S_INFO_WINDCODE"))
                if not symbol:
                    continue
                history_by_symbol.setdefault(symbol, []).append(
                    {
                        "symbol": symbol,
                        "trade_date": _normalize_trade_date(row.get("TRADE_DT")),
                        "open": to_float(row.get("S_DQ_OPEN")),
                        "high": to_float(row.get("S_DQ_HIGH")),
                        "low": to_float(row.get("S_DQ_LOW")),
                        "close": to_float(row.get("S_DQ_CLOSE")),
                        "prev_close": to_float(row.get("S_DQ_PRECLOSE")),
                        "pct_change": to_float(row.get("S_DQ_PCTCHANGE")) / 100.0,
                        "volume": to_float(row.get("S_DQ_VOLUME")),
                        "amount": to_float(row.get("S_DQ_AMOUNT")) * 1000.0,
                        "avg_price": to_float(row.get("S_DQ_AVGPRICE")),
                        "change": to_float(row.get("S_DQ_CHANGE")),
                        "upper_limit": to_float(row.get("S_DQ_LIMIT")),
                        "lower_limit": to_float(row.get("S_DQ_STOPPING")),
                    }
                )
    except SQLAlchemyError as exc:
        raise RuntimeError(f"wind_query_failed:{exc}") from exc

    for symbol, rows in list(history_by_symbol.items()):
        if len(rows) > lookback_days:
            history_by_symbol[symbol] = rows[-lookback_days:]
    return history_by_symbol


def _execute_history_batch(
    *,
    engine: Any,
    query: Any,
    symbols: list[str],
    start_trade_date: str,
    end_trade_date: str,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, WIND_QUERY_MAX_RETRIES + 2):
        try:
            with engine.connect() as connection:
                return list(
                    connection.execute(
                        query,
                        {
                            "symbols": symbols,
                            "start_trade_date": start_trade_date,
                            "end_trade_date": end_trade_date,
                        },
                    ).mappings()
                )
        except SQLAlchemyError as exc:
            last_error = exc
            engine.dispose()
            if attempt > WIND_QUERY_MAX_RETRIES:
                break
            sleep(WIND_QUERY_RETRY_SLEEP_SECONDS * attempt)
    if last_error is not None:
        raise last_error
    return []


def _chunked_symbols(symbols: list[str], batch_size: int) -> list[list[str]]:
    effective_batch_size = max(batch_size, 1)
    return [symbols[index : index + effective_batch_size] for index in range(0, len(symbols), effective_batch_size)]


@lru_cache(maxsize=2)
def _get_wind_engine(*, db_url: str, connect_timeout_seconds: int):
    if create_engine is None:
        raise RuntimeError("sqlalchemy_not_available")
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )


def _build_market_view(
    *,
    history: list[dict[str, Any]],
    trade_date: str,
    min_history_days: int,
) -> dict[str, Any]:
    effective_history = [row for row in history if str(row.get("trade_date", "")) <= trade_date]
    if not effective_history:
        raise RuntimeError("wind_history_empty_after_trade_date_filter")

    latest = effective_history[-1]
    closes = [to_float(row.get("close")) for row in effective_history if to_float(row.get("close")) > 0]
    highs = [to_float(row.get("high")) for row in effective_history if to_float(row.get("high")) > 0]
    lows = [to_float(row.get("low")) for row in effective_history if to_float(row.get("low")) > 0]
    volumes = [max(to_float(row.get("volume")), 0.0) for row in effective_history]
    amounts = [max(to_float(row.get("amount")), 0.0) for row in effective_history]

    close = to_float(latest.get("close"))
    amount = max(to_float(latest.get("amount")), 0.0)
    volume = max(to_float(latest.get("volume")), 0.0)

    ma5 = _mean_tail(closes, 5)
    ma10 = _mean_tail(closes, 10)
    ma20 = _mean_tail(closes, 20)
    ma60 = _mean_tail(closes, 60)
    ma120 = _mean_tail(closes, 120)

    prev_high_20 = _max_prev_window(highs, 20)
    prev_high_60 = _max_prev_window(highs, 60)
    avg_volume_5 = _mean_prev_window(volumes, 5)
    avg_amount_20 = _mean_prev_window(amounts, 20)

    returns = _daily_returns(closes)
    return_5d = _window_return(closes, 5)
    return_10d = _window_return(closes, 10)
    return_20d = _window_return(closes, 20)
    relative_volume = safe_div(volume, avg_volume_5, 1.0)
    relative_amount = safe_div(amount, avg_amount_20, 1.0)
    volatility_20d = pstdev(returns[-20:]) if len(returns) >= 2 else 0.0
    atr_14 = _average_true_range(effective_history, 14)

    price_vs_ma20 = safe_div(close - ma20, ma20)
    price_vs_20d_high = safe_div(close - prev_high_20, prev_high_20)
    price_vs_60d_high = safe_div(close - prev_high_60, prev_high_60)
    ma_alignment_score = (
        float(close >= ma5)
        + float(ma5 >= ma10 if ma10 > 0 else close >= ma5)
        + float(ma10 >= ma20 if ma20 > 0 else close >= ma10)
        + float(ma20 >= ma60 if ma60 > 0 else close >= ma20)
    ) / 4.0

    ret5_score = _linear_score(return_5d, -0.08, 0.12)
    ret10_score = _linear_score(return_10d, -0.12, 0.18)
    ret20_score = _linear_score(return_20d, -0.18, 0.30)
    relative_volume_score = _linear_score(relative_volume, 0.80, 2.50)
    amount_score = _linear_score(math.log10(amount + 1.0), 8.0, 10.0)
    amount_trend_score = _linear_score(relative_amount, 0.80, 2.50)
    stability_score = 1.0 - _linear_score(volatility_20d, 0.02, 0.06)
    breakout_20_score = _linear_score(price_vs_20d_high, -0.08, 0.03)
    breakout_60_score = _linear_score(price_vs_60d_high, -0.15, 0.05)

    score_ready = len(effective_history) >= min_history_days
    momentum_score = clamp(
        ret5_score * 0.25
        + ret10_score * 0.25
        + ret20_score * 0.30
        + ma_alignment_score * 0.20,
        0.0,
        1.0,
    )
    breakout_score = clamp(
        breakout_20_score * 0.50
        + breakout_60_score * 0.20
        + relative_volume_score * 0.15
        + ma_alignment_score * 0.15,
        0.0,
        1.0,
    )
    liquidity_score = clamp(
        amount_score * 0.55
        + relative_volume_score * 0.20
        + amount_trend_score * 0.15
        + stability_score * 0.10,
        0.0,
        1.0,
    )
    turnover_rate_proxy = clamp(relative_amount * 0.04, 0.0, 0.20)
    trend_strength_score = clamp(momentum_score * 0.55 + breakout_score * 0.45, 0.0, 1.0)

    flags: list[str] = []
    if return_20d >= 0.10:
        flags.append("momentum_20d")
    if price_vs_20d_high >= -0.02:
        flags.append("near_20d_high")
    if relative_volume >= 1.50:
        flags.append("volume_expansion")
    if close >= ma20 > 0:
        flags.append("above_ma20")
    if ma60 > 0 and close >= ma60:
        flags.append("above_ma60")
    if volatility_20d <= 0.025:
        flags.append("low_volatility")

    technical_summary = (
        f"close={close:.2f}, 5d={return_5d:.1%}, 20d={return_20d:.1%}, "
        f"vs_ma20={price_vs_ma20:.1%}, vs_20d_high={price_vs_20d_high:.1%}, "
        f"vol_ratio={relative_volume:.2f}, amount_ratio={relative_amount:.2f}, vol20={volatility_20d:.1%}"
    )

    return {
        "market_data_source": "wind:ASHAREEODPRICES",
        "market_data_trade_date": latest.get("trade_date", trade_date),
        "market_data_ready": score_ready,
        "open_price": to_float(latest.get("open")),
        "high_price": to_float(latest.get("high")),
        "low_price": to_float(latest.get("low")),
        "last_price": close,
        "prev_close": to_float(latest.get("prev_close")),
        "upper_limit": to_float(latest.get("upper_limit")),
        "lower_limit": to_float(latest.get("lower_limit")),
        "avg_price": to_float(latest.get("avg_price")),
        "volume": volume,
        "amount": amount,
        "daily_change": to_float(latest.get("change")),
        "daily_pct_change": to_float(latest.get("pct_change")),
        "relative_volume": relative_volume,
        "relative_amount": relative_amount,
        "turnover_rate_proxy": turnover_rate_proxy,
        "momentum_score": momentum_score,
        "breakout_score": breakout_score,
        "liquidity_score": liquidity_score,
        "trend_strength_score": trend_strength_score,
        "volatility_score": _linear_score(volatility_20d, 0.01, 0.05),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "price_vs_ma20": price_vs_ma20,
        "price_vs_20d_high": price_vs_20d_high,
        "price_vs_60d_high": price_vs_60d_high,
        "return_5d": return_5d,
        "return_10d": return_10d,
        "return_20d": return_20d,
        "volatility_20d": volatility_20d,
        "atr_14": atr_14,
        "technical_flags": join_tags(flags),
        "technical_summary": technical_summary,
    }


def _merge_market_view(
    *,
    raw_row: dict[str, Any],
    market_view: dict[str, Any],
    prefer_source_prices: bool,
) -> dict[str, Any]:
    merged = dict(raw_row)
    merged["market_data_source"] = market_view.get("market_data_source", merged.get("market_data_source", "snapshot"))
    merged["market_data_trade_date"] = market_view.get("market_data_trade_date", merged.get("market_data_trade_date", ""))
    merged["market_data_ready"] = bool(market_view.get("market_data_ready", False))

    for key in (
        "open_price",
        "high_price",
        "low_price",
        "last_price",
        "prev_close",
        "upper_limit",
        "lower_limit",
        "avg_price",
        "volume",
        "amount",
        "daily_change",
        "daily_pct_change",
        "relative_volume",
        "relative_amount",
        "turnover_rate_proxy",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "ma120",
        "price_vs_ma20",
        "price_vs_20d_high",
        "price_vs_60d_high",
        "return_5d",
        "return_10d",
        "return_20d",
        "volatility_20d",
        "volatility_score",
        "atr_14",
        "technical_flags",
        "technical_summary",
        "trend_strength_score",
    ):
        if key in {"last_price", "prev_close", "upper_limit", "lower_limit", "amount", "volume"}:
            if prefer_source_prices or merged.get(key) in {"", None}:
                merged[key] = market_view.get(key, merged.get(key))
            continue
        merged[key] = market_view.get(key, merged.get(key))

    if bool(market_view.get("market_data_ready")):
        merged["momentum_score"] = market_view.get("momentum_score", merged.get("momentum_score"))
        merged["breakout_score"] = market_view.get("breakout_score", merged.get("breakout_score"))
        merged["liquidity_score"] = market_view.get("liquidity_score", merged.get("liquidity_score"))
        if to_float(merged.get("turnover_rate")) <= 0:
            merged["turnover_rate"] = market_view.get("turnover_rate_proxy", merged.get("turnover_rate", 0.0))
    else:
        merged.setdefault("turnover_rate_proxy", market_view.get("turnover_rate_proxy", 0.0))
        if merged.get("technical_summary") in {"", None}:
            merged["technical_summary"] = market_view.get("technical_summary", "")

    return merged


def _to_db_trade_date(value: str) -> str:
    return value.replace("-", "")


def _normalize_trade_date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text_value = str(value).strip()
    if len(text_value) == 8 and text_value.isdigit():
        return f"{text_value[:4]}-{text_value[4:6]}-{text_value[6:8]}"
    return text_value


def _mean_tail(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    tail = values[-window:] if len(values) >= window else values
    return sum(tail) / max(len(tail), 1)


def _mean_prev_window(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    start_index = max(len(values) - window - 1, 0)
    tail = values[start_index:-1]
    if not tail:
        tail = values[:-1] or values
    return sum(tail) / max(len(tail), 1)


def _max_prev_window(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    start_index = max(len(values) - window - 1, 0)
    tail = values[start_index:-1]
    if not tail:
        tail = values[:-1] or values
    return max(tail)


def _window_return(closes: list[float], window: int) -> float:
    if len(closes) <= 1:
        return 0.0
    base_index = max(len(closes) - window - 1, 0)
    base = closes[base_index]
    latest = closes[-1]
    return safe_div(latest - base, base)


def _daily_returns(closes: list[float]) -> list[float]:
    returns: list[float] = []
    for prev_close, close in zip(closes[:-1], closes[1:]):
        returns.append(safe_div(close - prev_close, prev_close))
    return returns


def _average_true_range(history: list[dict[str, Any]], window: int) -> float:
    if not history:
        return 0.0
    true_ranges: list[float] = []
    previous_close = None
    for row in history:
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        close = to_float(row.get("close"))
        if previous_close is None:
            true_range = max(high - low, 0.0)
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
        previous_close = close
    tail = true_ranges[-window:] if len(true_ranges) >= window else true_ranges
    return sum(tail) / max(len(tail), 1)


def _linear_score(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return clamp((value - lower) / (upper - lower), 0.0, 1.0)
