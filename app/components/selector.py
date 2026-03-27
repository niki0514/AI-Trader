from __future__ import annotations

import math
import re
from typing import Any

from app.a_share import enrich_security_info, infer_board, infer_exchange, is_limit_up, normalize_symbol
from app.pipeline.io import SelectorStageInput
from app.pipeline.outputs import SelectorStageOutput, TechCandidateRow
from app.pipeline.results import StageResult
from app.stock_screen import build_stock_screen_request_id, load_stock_screen_settings, run_stock_screen_query
from app.utils import clamp, join_tags, to_bool, to_float, to_int


KEY_SUFFIX_RE = re.compile(r"[\(\（].*?[\)\）]|\[[^\]]+\]")


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    stage_input = SelectorStageInput.from_payload(payload)
    selector_watchlist, selector_source, stock_screen_result = _resolve_selector_watchlist(
        ctx=ctx,
        stage_input=stage_input,
    )
    tech_candidates = _build_candidates(
        ctx=ctx,
        watchlist=selector_watchlist,
        source=selector_source,
    )
    if selector_source == "stock_screen":
        selector_strategy = "stock_screen_api"
    elif selector_source == "candidate_pool":
        selector_strategy = "candidate_pool_passthrough"
    else:
        selector_strategy = "snapshot_rules_and_technical_filter"

    return StageResult(
        updates=SelectorStageOutput(
            tech_candidates=tech_candidates,
            selector_watchlist=selector_watchlist,
            selector_source=selector_source,
            stock_screen_result=stock_screen_result,
            selector_failed=False,
        ),
        stage_note=f"{selector_strategy}; source={selector_source}; candidates={len(tech_candidates)}",
    )


def _resolve_selector_watchlist(
    *,
    ctx: Any,
    stage_input: SelectorStageInput,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    snapshots = stage_input.snapshots
    snapshot = snapshots.snapshot
    snapshot_market = snapshots.snapshot_market
    selection_config = ctx.config.get("selection", {})
    selector_query = snapshots.selector_query
    stock_screen_query = selection_config.get("stock_screen", {})
    source = str(selector_query.get("source") or selection_config.get("source") or "snapshot").strip().lower()
    query_keyword = str(selector_query.get("keyword") or stock_screen_query.get("keyword") or "").strip()
    source_snapshot = snapshots.effective_snapshot

    if source in {"candidate_pool", "watchlist"}:
        watchlist = list(snapshots.watchlist)
        return watchlist, "candidate_pool", {}

    use_stock_screen = source in {"stock_screen", "eastmoney", "dongcai"} or bool(query_keyword)
    if not use_stock_screen:
        watchlist = list(source_snapshot.get("watchlist", []))
        return watchlist, "snapshot", {}

    settings = load_stock_screen_settings(ctx.config)
    top_n = max(to_int(selection_config.get("top_n"), 4), 1)
    market = str(selector_query.get("market") or stock_screen_query.get("market") or "A股").strip()
    page_size = max(
        to_int(selector_query.get("page_size"), to_int(stock_screen_query.get("page_size"), max(top_n * 5, top_n))),
        top_n,
    )
    fetch_all = to_bool(selector_query.get("fetch_all"), to_bool(stock_screen_query.get("fetch_all"), False))
    if not query_keyword:
        raise ValueError("selection.stock_screen.keyword is required when selector source is stock_screen")

    request_id = str(selector_query.get("request_id") or build_stock_screen_request_id(query_keyword, market))
    result = run_stock_screen_query(
        keyword=query_keyword,
        settings=settings,
        market=market,
        page_no=1,
        page_size=page_size,
        fetch_all=fetch_all,
        request_id=request_id,
        export_dir=ctx.output_dir / "selector_stock_screen" / request_id,
    )
    watchlist = _stock_screen_rows_to_watchlist(result.get("rows", []))
    return watchlist, "stock_screen", {
        "request_id": result.get("request_id", ""),
        "keyword": result.get("keyword", ""),
        "effective_keyword": result.get("effective_keyword", ""),
        "market": result.get("market", ""),
        "total": to_int(result.get("total")),
        "row_count": to_int(result.get("row_count")),
        "page_size": to_int(result.get("page_size")),
        "pages_fetched": to_int(result.get("pages_fetched")),
        "parser_text": result.get("parser_text", ""),
        "artifacts": result.get("artifacts", {}),
    }


def _build_candidates(ctx: Any, watchlist: list[dict[str, Any]], source: str = "snapshot") -> list[TechCandidateRow]:
    degrade = ctx.config.get("degrade", {})
    if degrade.get("disable_selector", False):
        return []
    if source == "stock_screen":
        return _build_stock_screen_candidates(ctx=ctx, watchlist=watchlist)
    return _build_snapshot_candidates(ctx=ctx, watchlist=watchlist, source=source)


def _build_snapshot_candidates(ctx: Any, watchlist: list[dict[str, Any]], source: str = "snapshot") -> list[TechCandidateRow]:
    selection_config = ctx.config.get("selection", {})
    a_share_selection = ctx.config.get("a_share", {}).get("selection", {})
    top_n = to_int(selection_config.get("top_n"), 4)
    rule_filter_mode = _resolve_snapshot_rule_filter_mode(selection_config, source)
    tech_floor = to_float(selection_config.get("tech_score_floor"), 0.62)
    liquidity_floor = to_float(selection_config.get("liquidity_score_floor"), 0.50)
    momentum_weight = to_float(selection_config.get("momentum_weight"), 0.30)
    breakout_weight = to_float(selection_config.get("breakout_weight"), 0.20)
    liquidity_weight = to_float(selection_config.get("liquidity_weight"), 0.15)
    turnover_weight = to_float(a_share_selection.get("turnover_weight"), 0.15)
    relative_volume_weight = to_float(a_share_selection.get("relative_volume_weight"), 0.10)
    amount_weight = to_float(a_share_selection.get("amount_weight"), 0.10)

    min_turnover_rate = to_float(a_share_selection.get("min_turnover_rate"), 0.02)
    preferred_turnover_rate = to_float(a_share_selection.get("preferred_turnover_rate"), 0.06)
    min_relative_volume = to_float(a_share_selection.get("min_relative_volume"), 1.0)
    min_amount = to_float(a_share_selection.get("min_amount"), 300000000.0)
    near_limit_up_guard_pct = to_float(a_share_selection.get("near_limit_up_guard_pct"), 0.985)
    near_limit_up_penalty = to_float(a_share_selection.get("near_limit_up_penalty"), 0.18)

    rows: list[TechCandidateRow] = []
    for raw_candidate in watchlist:
        security = enrich_security_info(raw_candidate, ctx.config)
        symbol = security["symbol"]
        if not symbol:
            continue

        momentum_score = clamp(to_float(raw_candidate.get("momentum_score"), 0.0), 0.0, 1.0)
        breakout_score = clamp(to_float(raw_candidate.get("breakout_score"), momentum_score), 0.0, 1.0)
        liquidity_score = clamp(
            to_float(raw_candidate.get("liquidity_score"), 0.55),
            0.0,
            1.0,
        )
        turnover_rate = max(security["turnover_rate"], 0.0)
        relative_volume = max(security["relative_volume"], 0.0)
        amount = max(security["amount"], 0.0)
        turnover_score = clamp(turnover_rate / max(preferred_turnover_rate, 1e-6), 0.0, 1.0)
        relative_volume_score = clamp(relative_volume / max(min_relative_volume * 2.0, 1.0), 0.0, 1.0)
        amount_score = clamp(math.log10(max(amount, 1.0)) / 10.0, 0.0, 1.0)
        near_upper_limit = is_limit_up(
            security["last_price"],
            security["upper_limit"],
            tolerance=max(0.0, 1.0 - near_limit_up_guard_pct),
        )

        tech_score = clamp(
            momentum_score * momentum_weight
            + breakout_score * breakout_weight
            + liquidity_score * liquidity_weight,
            0.0,
            1.0,
        )
        tech_score = clamp(
            tech_score
            + turnover_score * turnover_weight
            + relative_volume_score * relative_volume_weight
            + amount_score * amount_weight
            - (near_limit_up_penalty if near_upper_limit else 0.0),
            0.0,
            1.0,
        )

        trigger_tags: list[str] = []
        if momentum_score >= 0.75:
            trigger_tags.append("momentum")
        if breakout_score >= 0.70:
            trigger_tags.append("breakout")
        if liquidity_score >= 0.65:
            trigger_tags.append("liquidity")
        if turnover_rate >= preferred_turnover_rate:
            trigger_tags.append("turnover")
        if relative_volume >= 1.5:
            trigger_tags.append("volume_ratio")
        if near_upper_limit:
            trigger_tags.append("near_limit_up")
        if security["board"] == "CHINEXT":
            trigger_tags.append("chinext")
        elif security["board"] == "STAR":
            trigger_tags.append("star")
        technical_flags = [item for item in str(security.get("technical_flags", "")).split("|") if item]
        for flag in technical_flags:
            if flag not in trigger_tags:
                trigger_tags.append(flag)

        full_rule_pass = (
            tech_score >= tech_floor
            and liquidity_score >= liquidity_floor
            and turnover_rate >= min_turnover_rate
            and relative_volume >= min_relative_volume
            and amount >= min_amount
            and not security["is_st"]
            and not security["suspended"]
            and not near_upper_limit
        )
        if rule_filter_mode == "none":
            rule_pass = True
        elif rule_filter_mode == "minimal":
            rule_pass = security["last_price"] > 0 and not security["suspended"]
        else:
            rule_pass = full_rule_pass
        rows.append(
            TechCandidateRow(
                trade_date=ctx.trade_date,
                symbol=symbol,
                name=security["name"],
                sector=security["industry"],
                board=security["board"],
                last_price=security["last_price"],
                prev_close=security["prev_close"],
                upper_limit=security["upper_limit"] or 0.0,
                lower_limit=security["lower_limit"] or 0.0,
                rule_pass=rule_pass,
                tech_score=tech_score,
                momentum_score=momentum_score,
                breakout_score=breakout_score,
                liquidity_score=liquidity_score,
                turnover_rate=turnover_rate,
                turnover_rate_proxy=to_float(security.get("turnover_rate_proxy")),
                relative_volume=relative_volume,
                relative_amount=to_float(security.get("relative_amount")),
                amount=amount,
                daily_pct_change=to_float(security.get("daily_pct_change")),
                return_5d=to_float(security.get("return_5d")),
                return_20d=to_float(security.get("return_20d")),
                ma20=to_float(security.get("ma20")),
                ma60=to_float(security.get("ma60")),
                price_vs_ma20=to_float(security.get("price_vs_ma20")),
                price_vs_20d_high=to_float(security.get("price_vs_20d_high")),
                volatility_20d=to_float(security.get("volatility_20d")),
                near_upper_limit=near_upper_limit,
                is_st=security["is_st"],
                suspended=security["suspended"],
                list_days=int(security["list_days"]),
                market_data_source=str(security.get("market_data_source", "snapshot")),
                technical_flags=str(security.get("technical_flags", "")),
                technical_summary=str(security.get("technical_summary", "")),
                trigger_tags=join_tags(trigger_tags),
            )
        )

    ranked = sorted(
        rows,
        key=lambda item: (
            item.rule_pass,
            item.tech_score,
            item.relative_volume,
            item.turnover_rate,
        ),
        reverse=True,
    )
    if top_n <= 0:
        return ranked
    return ranked[:top_n]


def _build_stock_screen_candidates(ctx: Any, watchlist: list[dict[str, Any]]) -> list[TechCandidateRow]:
    selection_config = ctx.config.get("selection", {})
    top_n = to_int(selection_config.get("top_n"), 4)
    rows: list[TechCandidateRow] = []
    total = max(len(watchlist), 1)

    for index, raw_candidate in enumerate(watchlist, start=1):
        security = enrich_security_info(raw_candidate, ctx.config)
        symbol = security["symbol"]
        if not symbol:
            continue

        rank_score = 1.0 - ((index - 1) / total)
        pct_change = to_float(raw_candidate.get("daily_pct_change"))
        turnover_rate = max(to_float(raw_candidate.get("turnover_rate")), 0.0)
        relative_volume = max(to_float(raw_candidate.get("relative_volume"), 1.0), 0.0)
        amount = max(to_float(raw_candidate.get("amount")), 0.0)
        momentum_score = clamp(rank_score * 0.65 + _linear_score(pct_change, -0.03, 0.08) * 0.35, 0.0, 1.0)
        breakout_score = clamp(rank_score * 0.70 + _linear_score(relative_volume, 0.80, 2.50) * 0.30, 0.0, 1.0)
        liquidity_score = clamp(
            _linear_score(turnover_rate, 0.01, 0.08) * 0.45
            + _linear_score(relative_volume, 0.80, 2.50) * 0.20
            + _linear_score(math.log10(amount + 1.0), 8.0, 10.0) * 0.35,
            0.0,
            1.0,
        )
        tech_score = clamp(
            momentum_score * 0.40 + breakout_score * 0.30 + liquidity_score * 0.30,
            0.0,
            1.0,
        )

        trigger_tags = ["stock_screen"]
        if momentum_score >= 0.70:
            trigger_tags.append("upstream_rank")
        if relative_volume >= 1.50:
            trigger_tags.append("volume_ratio")
        if turnover_rate >= 0.03:
            trigger_tags.append("turnover")
        if security["board"] == "CHINEXT":
            trigger_tags.append("chinext")
        elif security["board"] == "STAR":
            trigger_tags.append("star")

        rows.append(
            TechCandidateRow(
                trade_date=ctx.trade_date,
                symbol=symbol,
                name=security["name"],
                sector=security["industry"],
                board=security["board"],
                last_price=security["last_price"],
                prev_close=security["prev_close"],
                upper_limit=security["upper_limit"] or 0.0,
                lower_limit=security["lower_limit"] or 0.0,
                rule_pass=True,
                tech_score=tech_score,
                momentum_score=momentum_score,
                breakout_score=breakout_score,
                liquidity_score=liquidity_score,
                turnover_rate=turnover_rate,
                turnover_rate_proxy=to_float(security.get("turnover_rate_proxy")),
                relative_volume=relative_volume,
                relative_amount=to_float(security.get("relative_amount")),
                amount=amount,
                daily_pct_change=pct_change,
                return_5d=0.0,
                return_20d=0.0,
                ma20=0.0,
                ma60=0.0,
                price_vs_ma20=0.0,
                price_vs_20d_high=0.0,
                volatility_20d=0.0,
                near_upper_limit=False,
                is_st=security["is_st"],
                suspended=security["suspended"],
                list_days=int(security["list_days"]),
                market_data_source="eastmoney_stock_screen",
                technical_flags="",
                technical_summary=str(raw_candidate.get("selector_summary") or raw_candidate.get("stock_screen_summary") or ""),
                trigger_tags=join_tags(trigger_tags),
            )
        )

    if top_n <= 0:
        return rows
    return rows[:top_n]


def _resolve_snapshot_rule_filter_mode(selection_config: dict[str, Any], source: str) -> str:
    configured = str(selection_config.get("rule_filter") or "").strip().lower()
    if configured in {"none", "minimal", "full"}:
        return configured
    if source == "candidate_pool":
        return "minimal"
    return "full"


def _stock_screen_rows_to_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    watchlist: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        symbol = _resolve_stock_screen_symbol(row)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        last_price = _metric_value(row, "最新价", "最新", "收盘价", "现价")
        pct_change = _metric_value(row, "涨跌幅", "今日涨幅", "涨幅", pct=True)
        prev_close = _metric_value(row, "昨收", "昨收盘", "昨收价")
        if prev_close <= 0 and last_price > 0 and abs(pct_change) < 0.95:
            prev_close = last_price / (1.0 + pct_change) if abs(1.0 + pct_change) > 1e-8 else last_price

        amount = _metric_value(row, "成交额", "成交金额", "成交额(元)", unit_multiplier=1.0)
        if amount <= 0:
            amount = _metric_value(row, "成交额(亿)", unit_multiplier=100000000.0)

        turnover_rate = _metric_value(row, "换手率", pct=True)
        relative_volume = _metric_value(row, "量比", "量比值")
        name = _text_value(row, "股票简称", "证券简称", "名称", "股票名称")
        sector = _text_value(row, "所属行业", "行业", "申万行业", "行业板块")

        selector_summary = (
            f"rank={index}, latest={last_price:.2f}" if last_price > 0 else f"rank={index}"
        )
        watchlist.append(
            {
                "symbol": symbol,
                "name": name,
                "sector": sector or "UNKNOWN",
                "exchange": infer_exchange(symbol),
                "board": infer_board(symbol),
                "last_price": last_price,
                "prev_close": prev_close,
                "amount": amount,
                "turnover_rate": turnover_rate,
                "relative_volume": relative_volume if relative_volume > 0 else 1.0,
                "list_days": 9999,
                "suspended": False,
                "is_st": "ST" in name.upper(),
                "daily_pct_change": pct_change,
                "selector_summary": selector_summary,
                "selector_rank": index,
                "selector_source": "eastmoney_stock_screen",
            }
        )
    return watchlist


def _resolve_stock_screen_symbol(row: dict[str, Any]) -> str:
    value = _text_value(row, "股票代码", "证券代码", "代码", "股票代码[SECURITY_CODE]", "证券代码[SECURITY_CODE]")
    symbol = normalize_symbol(value)
    if not symbol:
        return ""
    if "." in symbol:
        return symbol
    if symbol.startswith(("60", "68", "90")):
        return f"{symbol}.SH"
    if symbol.startswith(("00", "20", "30", "12")):
        return f"{symbol}.SZ"
    if symbol.startswith(("43", "83", "87")):
        return f"{symbol}.BJ"
    return symbol


def _text_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        for value in _candidate_row_values(row, key):
            if value not in {"", None}:
                return str(value).strip()
    return ""


def _metric_value(
    row: dict[str, Any],
    *keys: str,
    pct: bool = False,
    unit_multiplier: float = 1.0,
) -> float:
    for key in keys:
        for value in _candidate_row_values(row, key):
            if value in {"", None}:
                continue
            text = str(value).strip().replace(",", "")
            if not text or text in {"--", "-"}:
                continue
            effective_pct = pct
            if text.endswith("%"):
                text = text[:-1].strip()
                effective_pct = True
            try:
                numeric = _parse_metric_number(text) * unit_multiplier
            except ValueError:
                continue
            return numeric / 100.0 if effective_pct else numeric
    return 0.0


def _candidate_row_values(row: dict[str, Any], key: str) -> list[Any]:
    if key in row:
        return [row.get(key)]

    normalized_target = _normalize_row_key(key)
    values: list[Any] = []
    for row_key, value in row.items():
        if _normalize_row_key(str(row_key)) == normalized_target:
            values.append(value)
    return values


def _normalize_row_key(value: str) -> str:
    normalized = KEY_SUFFIX_RE.sub("", str(value or "").strip())
    return normalized.replace(" ", "").upper()


def _parse_metric_number(value: str) -> float:
    text = str(value).strip().replace(",", "")
    multiplier = 1.0
    if text.endswith("万亿"):
        multiplier = 1000000000000.0
        text = text[:-2]
    elif text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    return float(text) * multiplier


def _linear_score(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return clamp((value - lower) / (upper - lower), 0.0, 1.0)
