from __future__ import annotations

from typing import Any

from app.a_share import is_limit_up
from app.adapters import AnalystLLMError, request_analyst_text, write_csv
from app.contracts import AI_INSIGHT_FIELDS
from app.utils import clamp, index_by, join_tags, to_float


def run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("snapshot", {})
    tech_candidates = list(payload.get("tech_candidates", []))
    positions_by_symbol = index_by(list(payload.get("positions_prev", [])), "symbol")
    event_lookup = index_by(list(snapshot.get("recent_events", [])), "symbol")
    fundamental_lookup = index_by(list(snapshot.get("fundamentals", [])), "symbol")

    analyst_failed = False
    stage_label = "local_composite"
    llm_live_enabled = bool(ctx.config.get("llm", {}).get("enable_live", False))

    ai_insights: list[dict[str, Any]] = []
    for candidate in tech_candidates:
        if not candidate.get("rule_pass", False):
            continue

        symbol = str(candidate.get("symbol", ""))
        event_view = event_lookup.get(symbol, {})
        fundamental_view = fundamental_lookup.get(symbol, {})
        turnover_rate = to_float(candidate.get("turnover_rate"))
        relative_volume = to_float(candidate.get("relative_volume"), 1.0)
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
            to_float(candidate.get("tech_score")) * 0.45
            + news_event_score * 0.30
            + fundamental_score * 0.25
            + min(turnover_rate / 0.10, 1.0) * 0.03
            + min(relative_volume / 2.0, 1.0) * 0.02
            - (0.08 if near_upper_limit else 0.0),
            0.0,
            1.0,
        )

        held = symbol in positions_by_symbol
        build_floor = to_float(ctx.config.get("decision", {}).get("build_score_floor"), 0.68)
        add_floor = to_float(ctx.config.get("decision", {}).get("add_score_floor"), 0.75)
        action_hint = "HOLD"
        if held and combined_score >= add_floor:
            action_hint = "ADD"
        elif (not held) and combined_score >= build_floor:
            action_hint = "BUILD"

        confidence = clamp(0.35 + combined_score * 0.60, 0.0, 0.99)
        risk_flags = _collect_risk_flags(news_event_score, fundamental_score, event_view, candidate, near_upper_limit)
        thesis = _build_local_thesis(candidate, event_view, fundamental_view, combined_score, turnover_rate, relative_volume)
        source = "local_composite"

        if llm_live_enabled:
            prompt = _build_prompt(candidate, event_view, fundamental_view, positions_by_symbol.get(symbol))
            try:
                thesis = request_analyst_text(ctx.config, prompt)
                source = "gmn_response_api"
                stage_label = "live_llm"
            except AnalystLLMError:
                analyst_failed = True
                source = "degraded_rule"
                stage_label = "degraded_rule"

        ai_insights.append(
            {
                "trade_date": ctx.trade_date,
                "symbol": symbol,
                "name": candidate.get("name", ""),
                "sector": candidate.get("sector", "UNKNOWN"),
                "board": candidate.get("board", "UNKNOWN"),
                "action_hint": action_hint,
                "confidence": confidence,
                "tech_score": to_float(candidate.get("tech_score")),
                "news_event_score": news_event_score,
                "fundamental_score": fundamental_score,
                "combined_score": combined_score,
                "thesis": thesis,
                "risk_flags": join_tags(risk_flags),
                "source": source,
                "analyst_failed": analyst_failed,
            }
        )

    if analyst_failed:
        for row in ai_insights:
            row["analyst_failed"] = True

    write_csv(ctx.artifact_path("ai_insights_t.csv"), ai_insights, AI_INSIGHT_FIELDS)

    next_payload = dict(payload)
    stage_notes = dict(payload.get("stage_notes", {}))
    stage_notes["analyst"] = f"{stage_label}; insights={len(ai_insights)}; analyst_failed={analyst_failed}"

    next_payload["ai_insights"] = ai_insights
    next_payload["analyst_failed"] = analyst_failed
    next_payload["stage_notes"] = stage_notes
    return next_payload


def _compute_fundamental_score(fundamental_view: dict[str, Any]) -> float:
    explicit_score = fundamental_view.get("fundamental_score")
    if explicit_score not in {"", None}:
        return clamp(to_float(explicit_score), 0.0, 1.0)
    growth_score = clamp(to_float(fundamental_view.get("growth_score"), 0.50), 0.0, 1.0)
    quality_score = clamp(to_float(fundamental_view.get("quality_score"), 0.50), 0.0, 1.0)
    valuation_score = clamp(to_float(fundamental_view.get("valuation_score"), 0.50), 0.0, 1.0)
    return clamp(growth_score * 0.40 + quality_score * 0.35 + valuation_score * 0.25, 0.0, 1.0)


def _collect_risk_flags(
    news_event_score: float,
    fundamental_score: float,
    event_view: dict[str, Any],
    candidate: dict[str, Any],
    near_upper_limit: bool,
) -> list[str]:
    flags: list[str] = []
    if news_event_score <= 0.40:
        flags.append("event_soft")
    if fundamental_score <= 0.45:
        flags.append("fundamental_soft")
    if str(event_view.get("sentiment", "")).lower() == "negative":
        flags.append("headline_negative")
    if bool(candidate.get("is_st")):
        flags.append("risk_warning")
    if bool(candidate.get("suspended")):
        flags.append("suspended")
    if near_upper_limit:
        flags.append("near_limit_up")
    return flags


def _build_local_thesis(
    candidate: dict[str, Any],
    event_view: dict[str, Any],
    fundamental_view: dict[str, Any],
    combined_score: float,
    turnover_rate: float,
    relative_volume: float,
) -> str:
    headline = str(event_view.get("headline", "no_recent_headline"))
    growth_score = to_float(fundamental_view.get("growth_score"), 0.50)
    quality_score = to_float(fundamental_view.get("quality_score"), 0.50)
    valuation_score = to_float(fundamental_view.get("valuation_score"), 0.50)
    return (
        f"board={candidate.get('board', 'UNKNOWN')}; "
        f"tech={to_float(candidate.get('tech_score')):.2f}; "
        f"turnover={turnover_rate:.2%}; "
        f"volume_ratio={relative_volume:.2f}; "
        f"event={to_float(event_view.get('event_score'), 0.50):.2f}; "
        f"fundamental(g={growth_score:.2f},q={quality_score:.2f},v={valuation_score:.2f}); "
        f"公告/事件={headline}; combined={combined_score:.2f}"
    )


def _build_prompt(
    candidate: dict[str, Any],
    event_view: dict[str, Any],
    fundamental_view: dict[str, Any],
    position_view: dict[str, Any] | None,
) -> str:
    position_text = "none"
    if position_view:
        position_text = (
            f"current_weight={to_float(position_view.get('current_weight')):.2%}, "
            f"unrealized_pnl_pct={to_float(position_view.get('unrealized_pnl_pct')):.2%}"
        )
    return (
        "你是A股短中线交易分析师，请结合盘面、公告与基本面给出简洁交易判断。\n"
        f"symbol={candidate.get('symbol')}\n"
        f"board={candidate.get('board', 'UNKNOWN')}\n"
        f"tech_score={to_float(candidate.get('tech_score')):.4f}\n"
        f"momentum_score={to_float(candidate.get('momentum_score')):.4f}\n"
        f"breakout_score={to_float(candidate.get('breakout_score')):.4f}\n"
        f"liquidity_score={to_float(candidate.get('liquidity_score')):.4f}\n"
        f"turnover_rate={to_float(candidate.get('turnover_rate')):.4f}\n"
        f"relative_volume={to_float(candidate.get('relative_volume'), 1.0):.4f}\n"
        f"recent_event_score={to_float(event_view.get('event_score'), 0.5):.4f}\n"
        f"recent_event_headline={event_view.get('headline', '')}\n"
        f"growth_score={to_float(fundamental_view.get('growth_score'), 0.5):.4f}\n"
        f"quality_score={to_float(fundamental_view.get('quality_score'), 0.5):.4f}\n"
        f"valuation_score={to_float(fundamental_view.get('valuation_score'), 0.5):.4f}\n"
        f"position={position_text}\n"
        "请输出一句简洁中文交易论点，说明驱动、风险和执行节奏。"
    )
