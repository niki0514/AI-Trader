from __future__ import annotations

import math
from typing import Any

from app.a_share import enrich_security_info, is_limit_up
from app.adapters import write_csv
from app.contracts import TECH_CANDIDATE_FIELDS
from app.utils import clamp, join_tags, to_float, to_int


def run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    selector_failed = False
    watchlist = list(payload.get("snapshot", {}).get("watchlist", []))

    try:
        tech_candidates = _build_candidates(ctx=ctx, watchlist=watchlist)
        strategy = "rules_and_technical_filter"
    except Exception as exc:
        selector_failed = True
        tech_candidates = []
        strategy = f"selector_failed:{exc}"

    write_csv(ctx.artifact_path("tech_candidates_t.csv"), tech_candidates, TECH_CANDIDATE_FIELDS)

    next_payload = dict(payload)
    stage_notes = dict(payload.get("stage_notes", {}))
    stage_notes["selector"] = f"{strategy}; candidates={len(tech_candidates)}"

    next_payload["tech_candidates"] = tech_candidates
    next_payload["selector_failed"] = selector_failed
    next_payload["stage_notes"] = stage_notes
    return next_payload


def _build_candidates(ctx: Any, watchlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    degrade = ctx.config.get("degrade", {})
    if degrade.get("disable_selector", False):
        return []

    selection_config = ctx.config.get("selection", {})
    a_share_selection = ctx.config.get("a_share", {}).get("selection", {})
    top_n = to_int(selection_config.get("top_n"), 4)
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

    rows: list[dict[str, Any]] = []
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

        rule_pass = (
            tech_score >= tech_floor
            and liquidity_score >= liquidity_floor
            and turnover_rate >= min_turnover_rate
            and relative_volume >= min_relative_volume
            and amount >= min_amount
            and not security["is_st"]
            and not security["suspended"]
            and not near_upper_limit
        )
        rows.append(
            {
                "trade_date": ctx.trade_date,
                "symbol": symbol,
                "name": security["name"],
                "sector": security["industry"],
                "board": security["board"],
                "last_price": security["last_price"],
                "prev_close": security["prev_close"],
                "upper_limit": security["upper_limit"] or 0.0,
                "lower_limit": security["lower_limit"] or 0.0,
                "rule_pass": rule_pass,
                "tech_score": tech_score,
                "momentum_score": momentum_score,
                "breakout_score": breakout_score,
                "liquidity_score": liquidity_score,
                "turnover_rate": turnover_rate,
                "relative_volume": relative_volume,
                "amount": amount,
                "near_upper_limit": near_upper_limit,
                "is_st": security["is_st"],
                "suspended": security["suspended"],
                "list_days": security["list_days"],
                "trigger_tags": join_tags(trigger_tags),
            }
        )

    ranked = sorted(
        rows,
        key=lambda item: (
            item["rule_pass"],
            item["tech_score"],
            item["relative_volume"],
            item["turnover_rate"],
        ),
        reverse=True,
    )
    return ranked[:top_n]
