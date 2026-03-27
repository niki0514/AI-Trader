from __future__ import annotations

import json
from typing import Any

from app.a_share import is_limit_up
from app.adapters import AnalystLLMError, request_agent_json, require_live_llm
from app.market_data import build_market_data_lookup, enrich_snapshot_with_market_data
from app.news_search import build_news_search_request_id, load_news_search_settings, run_news_search_query
from app.pipeline.io import AnalystStageInput
from app.pipeline.outputs import AIInsightRow, AnalystStageOutput, NewsSearchItemRow, NewsSearchView
from app.pipeline.results import StageResult
from app.utils import clamp, index_by, join_tags, to_bool, to_float, to_int


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    require_live_llm(ctx.config, "analyst")

    stage_input = AnalystStageInput.from_payload(payload)
    snapshot = stage_input.snapshots.snapshot
    tech_candidates = list(stage_input.tech_candidates)
    selector_source = stage_input.selector_source
    positions_by_symbol = index_by(stage_input.portfolio.positions_prev, "symbol")
    event_lookup = index_by(stage_input.snapshots.recent_events, "symbol")
    fundamental_lookup = index_by(stage_input.snapshots.fundamentals, "symbol")
    rule_pass_candidates = [candidate for candidate in tech_candidates if candidate.get("rule_pass", False)]
    market_data_by_symbol = _load_candidate_market_views(ctx=ctx, stage_input=stage_input, candidates=rule_pass_candidates)
    news_search_by_symbol = _load_candidate_news_views(ctx=ctx, candidates=rule_pass_candidates)

    ai_insights: list[AIInsightRow] = []
    for candidate in rule_pass_candidates:
        symbol = str(candidate.get("symbol", ""))
        news_search_view = news_search_by_symbol.get(symbol, {})
        event_view = _merge_event_view(
            base_event_view=event_lookup.get(symbol, {}),
            news_search_view=news_search_view,
            candidate=candidate,
        )
        fundamental_view = fundamental_lookup.get(symbol, {})
        ai_insights.append(
            _build_agent_insight(
                ctx=ctx,
                candidate=candidate,
                event_view=event_view,
                fundamental_view=fundamental_view,
                market_view=market_data_by_symbol.get(symbol, {}),
                news_search_view=news_search_view,
                position_view=positions_by_symbol.get(symbol),
                selector_source=selector_source,
            )
        )

    return StageResult(
        updates=AnalystStageOutput(
            ai_insights=ai_insights,
            analyst_news_search=news_search_by_symbol,
        ),
        stage_note=(
            f"llm_agent; insights={len(ai_insights)}; "
            f"wind_market_views={len(market_data_by_symbol)}; news_search={len(news_search_by_symbol)}"
        ),
    )


def _build_agent_insight(
    *,
    ctx: Any,
    candidate: dict[str, Any],
    event_view: dict[str, Any],
    fundamental_view: dict[str, Any],
    market_view: dict[str, Any],
    news_search_view: NewsSearchView | dict[str, Any],
    position_view: dict[str, Any] | None,
    selector_source: str,
) -> AIInsightRow:
    news_search_payload = news_search_view.to_dict() if isinstance(news_search_view, NewsSearchView) else dict(news_search_view)
    turnover_rate = to_float(candidate.get("turnover_rate"))
    relative_volume = to_float(candidate.get("relative_volume"), 1.0)
    market_technical_score = _compute_market_technical_score(candidate, market_view)
    near_upper_limit = bool(candidate.get("near_upper_limit")) or is_limit_up(
        to_float(candidate.get("last_price")),
        to_float(candidate.get("upper_limit"), 0.0) or None,
        0.015,
    )

    news_event_score = clamp(
        to_float(event_view.get("event_score"), to_float(candidate.get("tech_score"), 0.50)),
        0.0,
        1.0,
    )
    fundamental_score = _compute_fundamental_score(fundamental_view)
    combined_score = clamp(
        to_float(candidate.get("tech_score")) * 0.30
        + market_technical_score * 0.15
        + news_event_score * 0.30
        + fundamental_score * 0.25
        + min(turnover_rate / 0.10, 1.0) * 0.03
        + min(relative_volume / 2.0, 1.0) * 0.02
        - (0.08 if near_upper_limit else 0.0),
        0.0,
        1.0,
    )

    allowed_actions = ["ADD", "HOLD"] if position_view else ["BUILD", "HOLD"]
    prompt_payload = {
        "trade_date": ctx.trade_date,
        "allowed_actions": allowed_actions,
        "candidate": {
            "symbol": candidate.get("symbol"),
            "name": candidate.get("name"),
            "sector": candidate.get("sector"),
            "board": candidate.get("board"),
            "tech_score": to_float(candidate.get("tech_score")),
            "momentum_score": to_float(candidate.get("momentum_score")),
            "breakout_score": to_float(candidate.get("breakout_score")),
            "liquidity_score": to_float(candidate.get("liquidity_score")),
            "turnover_rate": turnover_rate,
            "relative_volume": relative_volume,
            "near_upper_limit": near_upper_limit,
            "selector_basis": selector_source,
        },
        "market_technical_view": {
            "source": market_view.get("market_data_source", "unavailable"),
            "market_technical_score": market_technical_score,
            "technical_summary": market_view.get("technical_summary", ""),
            "technical_flags": market_view.get("technical_flags", ""),
            "daily_pct_change": to_float(market_view.get("daily_pct_change")),
            "return_5d": to_float(market_view.get("return_5d")),
            "return_20d": to_float(market_view.get("return_20d")),
            "momentum_score": to_float(market_view.get("momentum_score")),
            "breakout_score": to_float(market_view.get("breakout_score")),
            "liquidity_score": to_float(market_view.get("liquidity_score")),
            "trend_strength_score": to_float(market_view.get("trend_strength_score")),
            "ma20": to_float(market_view.get("ma20")),
            "ma60": to_float(market_view.get("ma60")),
            "price_vs_ma20": to_float(market_view.get("price_vs_ma20")),
            "price_vs_20d_high": to_float(market_view.get("price_vs_20d_high")),
            "relative_volume": to_float(market_view.get("relative_volume")),
            "relative_amount": to_float(market_view.get("relative_amount")),
            "turnover_rate_proxy": to_float(market_view.get("turnover_rate_proxy")),
            "volatility_20d": to_float(market_view.get("volatility_20d")),
        },
        "news_search_view": {
            "source": news_search_payload.get("source", "eastmoney_news_search"),
            "query": news_search_payload.get("query", ""),
            "count": news_search_payload.get("count", 0),
            "news_search_score": to_float(news_search_payload.get("news_search_score")),
            "summary": news_search_payload.get("summary", ""),
            "top_items": news_search_payload.get("items", []),
        },
        "event_view": event_view,
        "fundamental_view": fundamental_view,
        "position_view": position_view or {},
        "features": {
            "market_technical_score": market_technical_score,
            "news_event_score": news_event_score,
            "fundamental_score": fundamental_score,
            "combined_score": combined_score,
        },
    }
    prompt = (
        "你是A股交易研判 agent。请基于输入数据给出结构化研判。"
        "你只能从 allowed_actions 中选择 action_hint。"
        "confidence 必须是 0 到 0.99 之间的小数。"
        "risk_flags 必须是字符串数组。"
        "thesis 需要是一句简洁中文交易论点。"
        "严格输出 JSON，不要输出 markdown。格式为："
        '{"action_hint":"BUILD","confidence":0.78,"risk_flags":["valuation_watch"],"thesis":"..."}。\n'
        f"{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    response = request_agent_json(ctx.config, prompt)
    if not isinstance(response, dict):
        raise AnalystLLMError("analyst agent response must be an object")

    action_hint = str(response.get("action_hint", "")).upper()
    if action_hint not in set(allowed_actions):
        raise AnalystLLMError(f"analyst agent invalid action for {candidate.get('symbol')}")

    raw_risk_flags = response.get("risk_flags", [])
    if isinstance(raw_risk_flags, str):
        risk_flags = [item.strip() for item in raw_risk_flags.split("|") if item.strip()]
    elif isinstance(raw_risk_flags, list):
        risk_flags = [str(item).strip() for item in raw_risk_flags if str(item).strip()]
    else:
        raise AnalystLLMError("analyst agent risk_flags must be list or string")

    thesis = str(response.get("thesis") or "").strip()
    if not thesis:
        raise AnalystLLMError("analyst agent thesis missing")

    return AIInsightRow(
        trade_date=ctx.trade_date,
        symbol=str(candidate.get("symbol", "")),
        name=str(candidate.get("name", "")),
        sector=str(candidate.get("sector", "UNKNOWN")),
        board=str(candidate.get("board", "UNKNOWN")),
        action_hint=action_hint,
        confidence=clamp(to_float(response.get("confidence")), 0.0, 0.99),
        tech_score=to_float(candidate.get("tech_score")),
        market_technical_score=market_technical_score,
        news_event_score=news_event_score,
        fundamental_score=fundamental_score,
        combined_score=combined_score,
        market_data_source=str(market_view.get("market_data_source", "snapshot")),
        technical_summary=str(market_view.get("technical_summary", "")),
        thesis=thesis,
        risk_flags=join_tags(risk_flags),
    )


def _load_candidate_market_views(
    *,
    ctx: Any,
    stage_input: AnalystStageInput,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}

    symbols = {str(candidate.get("symbol", "")).strip().upper() for candidate in candidates if str(candidate.get("symbol", "")).strip()}
    source_rows = _candidate_source_rows(stage_input)
    watchlist = []
    for symbol in symbols:
        row = source_rows.get(symbol)
        if row is None:
            candidate = next((item for item in candidates if str(item.get("symbol", "")).strip().upper() == symbol), {})
            row = {
                "symbol": symbol,
                "name": candidate.get("name", ""),
                "sector": candidate.get("sector", "UNKNOWN"),
                "last_price": to_float(candidate.get("last_price")),
                "prev_close": to_float(candidate.get("prev_close")),
                "amount": to_float(candidate.get("amount")),
                "turnover_rate": to_float(candidate.get("turnover_rate")),
                "relative_volume": to_float(candidate.get("relative_volume")),
                "list_days": to_float(candidate.get("list_days"), 9999),
                "suspended": bool(candidate.get("suspended", False)),
                "is_st": bool(candidate.get("is_st", False)),
            }
        watchlist.append(dict(row))

    market_snapshot = enrich_snapshot_with_market_data(
        {"trade_date": ctx.trade_date, "positions": [], "watchlist": watchlist},
        ctx.config,
        ctx.trade_date,
    )
    return build_market_data_lookup(market_snapshot)


def _candidate_source_rows(stage_input: AnalystStageInput) -> dict[str, dict[str, Any]]:
    rows = []
    rows.extend(list(stage_input.selector_watchlist))
    rows.extend(list(stage_input.snapshots.snapshot.get("watchlist", [])))
    rows.extend(list(stage_input.snapshots.snapshot_market.get("watchlist", [])))
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str((row or {}).get("symbol", "")).strip().upper()
        if symbol and symbol not in lookup:
            lookup[symbol] = dict(row)
    return lookup


def _load_candidate_news_views(
    *,
    ctx: Any,
    candidates: list[dict[str, Any]],
) -> dict[str, NewsSearchView]:
    if not candidates:
        return {}
    if not to_bool(ctx.config.get("news_search", {}).get("enabled"), True):
        return {}

    settings = load_news_search_settings(ctx.config)
    news_views: dict[str, NewsSearchView] = {}
    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        name = str(candidate.get("name") or symbol).strip()
        query = _build_candidate_news_query(name=name, symbol=symbol)
        request_id = build_news_search_request_id(f"{symbol}-{ctx.trade_date}")
        result = run_news_search_query(
            query=query,
            settings=settings,
            size=min(max(to_int(ctx.config.get("news_search", {}).get("default_size"), 6), 1), 8),
            request_id=request_id,
            export_dir=ctx.output_dir / "analyst_news_search" / symbol,
        )
        news_views[symbol] = _summarize_news_result(query=query, result=result)
    return news_views


def _build_candidate_news_query(*, name: str, symbol: str) -> str:
    code = symbol.split(".", 1)[0]
    return f"{name}({code}) 资讯"


def _summarize_news_result(*, query: str, result: dict[str, Any]) -> NewsSearchView:
    items = list(result.get("items", []))
    top_items = [
        NewsSearchItemRow(
            title=str(item.get("title") or ""),
            date=str(item.get("date") or ""),
            information_type=str(item.get("information_type") or ""),
            jump_url=str(item.get("jump_url") or ""),
            excerpt=str(item.get("trunk_excerpt") or item.get("trunk") or ""),
        )
        for item in items[:3]
    ]
    attention_ratio = (
        sum(1 for item in items if bool(item.get("index_attention"))) / len(items)
        if items
        else 0.0
    )
    rank_score = (
        sum(to_float(item.get("rank_score")) for item in items if item.get("rank_score") not in {"", None}) / max(len(items), 1)
        if items
        else 0.0
    )
    news_search_score = clamp(
        0.45
        + min(len(items), 5) * 0.05
        + attention_ratio * 0.10
        + min(rank_score / 100.0, 0.10),
        0.0,
        1.0,
    )
    summary = " | ".join(item.title for item in top_items if item.title)
    return NewsSearchView(
        source="eastmoney_news_search",
        query=query,
        count=len(items),
        news_search_score=news_search_score,
        summary=summary,
        items=top_items,
    )


def _merge_event_view(
    *,
    base_event_view: dict[str, Any],
    news_search_view: NewsSearchView | dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    news_search_payload = news_search_view.to_dict() if isinstance(news_search_view, NewsSearchView) else dict(news_search_view)
    merged = dict(base_event_view)
    base_score = (
        clamp(to_float(base_event_view.get("event_score")), 0.0, 1.0)
        if base_event_view.get("event_score") not in {"", None}
        else None
    )
    news_score = clamp(to_float(news_search_payload.get("news_search_score"), 0.50), 0.0, 1.0)
    merged["event_score"] = (
        clamp(base_score * 0.60 + news_score * 0.40, 0.0, 1.0)
        if base_score is not None
        else news_score
    )
    if not merged.get("headline"):
        merged["headline"] = news_search_payload.get("summary") or candidate.get("name", "")
    merged["news_search_count"] = int(news_search_payload.get("count", 0))
    merged["news_search_summary"] = news_search_payload.get("summary", "")
    merged["news_source"] = news_search_payload.get("source", "eastmoney_news_search")
    return merged


def _compute_fundamental_score(fundamental_view: dict[str, Any]) -> float:
    explicit_score = fundamental_view.get("fundamental_score")
    if explicit_score not in {"", None}:
        return clamp(to_float(explicit_score), 0.0, 1.0)
    growth_score = clamp(to_float(fundamental_view.get("growth_score"), 0.50), 0.0, 1.0)
    quality_score = clamp(to_float(fundamental_view.get("quality_score"), 0.50), 0.0, 1.0)
    valuation_score = clamp(to_float(fundamental_view.get("valuation_score"), 0.50), 0.0, 1.0)
    return clamp(growth_score * 0.40 + quality_score * 0.35 + valuation_score * 0.25, 0.0, 1.0)


def _compute_market_technical_score(candidate: dict[str, Any], market_view: dict[str, Any]) -> float:
    if not market_view:
        return clamp(to_float(candidate.get("tech_score"), 0.50), 0.0, 1.0)

    momentum_score = clamp(
        to_float(market_view.get("momentum_score"), to_float(candidate.get("momentum_score"), 0.50)),
        0.0,
        1.0,
    )
    breakout_score = clamp(
        to_float(market_view.get("breakout_score"), to_float(candidate.get("breakout_score"), momentum_score)),
        0.0,
        1.0,
    )
    liquidity_score = clamp(
        to_float(market_view.get("liquidity_score"), to_float(candidate.get("liquidity_score"), 0.50)),
        0.0,
        1.0,
    )
    trend_strength_score = clamp(
        to_float(market_view.get("trend_strength_score"), (momentum_score + breakout_score) / 2.0),
        0.0,
        1.0,
    )
    relative_volume_score = clamp(to_float(market_view.get("relative_volume")) / 2.0, 0.0, 1.0)
    price_vs_ma20_score = clamp((to_float(market_view.get("price_vs_ma20")) + 0.10) / 0.20, 0.0, 1.0)
    return clamp(
        momentum_score * 0.25
        + breakout_score * 0.20
        + liquidity_score * 0.20
        + trend_strength_score * 0.20
        + relative_volume_score * 0.10
        + price_vs_ma20_score * 0.05,
        0.0,
        1.0,
    )
