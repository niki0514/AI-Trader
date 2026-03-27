from __future__ import annotations

import json
from typing import Any

from app.adapters import request_agent_text, require_live_llm
from app.contracts import SELL_LIKE_ACTIONS
from app.pipeline.io import ReporterStageInput
from app.pipeline.outputs import MetricsSummary, ReporterStageOutput
from app.pipeline.results import StageResult
from app.utils import compute_sharpe_ratio, index_by, to_float


def run(ctx: Any, payload: dict[str, Any]) -> StageResult:
    require_live_llm(ctx.config, "reporter")

    stage_input = ReporterStageInput.from_payload(payload)
    trade_plan = list(stage_input.trade_plan)
    sim_fill = list(stage_input.sim_fill)
    positions_prev = index_by(stage_input.portfolio.positions_prev, "symbol")
    positions = list(stage_input.positions)
    nav = list(stage_input.nav)
    risk_events = list(stage_input.risk_events)
    nav_row = stage_input.nav_row

    metrics = _build_metrics(stage_input, trade_plan, sim_fill, positions_prev, nav)
    risk_report = _build_agent_risk_report(
        ctx=ctx,
        stage_input=stage_input,
        trade_plan=trade_plan,
        sim_fill=sim_fill,
        positions=positions,
        nav_row=nav_row,
        risk_events=risk_events,
        metrics=metrics,
    )

    return StageResult(
        updates=ReporterStageOutput(
            metrics=metrics,
            risk_report_markdown=risk_report,
        ),
        stage_note=f"llm_agent_report; intercepts={metrics.risk_intercept_count}; filled={metrics.filled_order_count}",
    )


def _build_metrics(
    stage_input: ReporterStageInput,
    trade_plan: list[dict[str, Any]],
    sim_fill: list[dict[str, Any]],
    positions_prev: dict[str, dict[str, Any]],
    nav: list[dict[str, Any]],
) -> MetricsSummary:
    nav_row = nav[-1] if nav else {}
    daily_returns = [to_float(item.get("daily_return")) for item in nav if item.get("daily_return") not in {"", None}]
    filled_orders = [row for row in sim_fill if row.get("status") == "FILLED"]

    profitable_sells = 0
    sell_count = 0
    for fill in filled_orders:
        if str(fill.get("action", "")).upper() not in SELL_LIKE_ACTIONS:
            continue
        sell_count += 1
        avg_cost = to_float(positions_prev.get(str(fill.get("symbol", "")), {}).get("avg_cost"))
        if to_float(fill.get("fill_price")) > avg_cost:
            profitable_sells += 1

    risk_intercept_count = len(
        [
            row
            for row in trade_plan
            if str(row.get("status", "")).upper() == "REJECTED" or str(row.get("cap_hit_reason", "")).strip()
        ]
    )

    return MetricsSummary(
        run_id=stage_input.run_id,
        trade_date=str(stage_input.snapshots.snapshot.get("trade_date") or nav_row.get("trade_date", "")),
        daily_return=to_float(nav_row.get("daily_return")),
        cum_return=to_float(nav_row.get("cum_return")),
        max_drawdown=to_float(nav_row.get("max_drawdown")),
        trading_fees=to_float(nav_row.get("trading_fees")),
        sharpe_ratio=compute_sharpe_ratio(daily_returns),
        win_rate=profitable_sells / sell_count if sell_count else 0.0,
        risk_intercept_count=risk_intercept_count,
        filled_order_count=len(filled_orders),
        accepted_order_count=len([row for row in trade_plan if row.get("status") == "ACCEPTED"]),
        limit_no_fill_count=len(
            [row for row in sim_fill if "limit_" in str(row.get("note", "")) and row.get("status") != "FILLED"]
        ),
        total_buy_orders=len([row for row in filled_orders if str(row.get("action", "")).upper() in {"BUILD", "ADD"}]),
        total_sell_orders=len([row for row in filled_orders if str(row.get("action", "")).upper() in SELL_LIKE_ACTIONS]),
        selector_failed=stage_input.selector_failed,
        risk_mode=stage_input.portfolio.risk_mode,
    )

def _build_agent_risk_report(
    *,
    ctx: Any,
    stage_input: ReporterStageInput,
    trade_plan: list[dict[str, Any]],
    sim_fill: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    nav_row: dict[str, Any],
    risk_events: list[dict[str, Any]],
    metrics: MetricsSummary,
) -> str:
    prompt_payload = {
        "run_id": ctx.run_id,
        "trade_date": ctx.trade_date,
        "risk_mode": stage_input.portfolio.risk_mode,
        "metrics": metrics.to_dict(),
        "risk_events": risk_events[:10],
        "sim_fill": sim_fill[:12],
        "positions": positions[:12],
        "nav_row": nav_row,
        "stage_notes": stage_input.stage_notes,
        "trade_plan_summary": [
            {
                "symbol": row.get("symbol"),
                "action": row.get("action"),
                "status": row.get("status"),
                "w_final": to_float(row.get("w_final")),
                "reason": row.get("reason"),
            }
            for row in trade_plan[:12]
        ],
    }
    prompt = (
        "你是A股交易日报 agent。请基于输入内容输出一份简洁、专业、结构清晰的 markdown 日报摘要。"
        "请只保留 4 个短章节：当日概览、关键风控事件、成交执行、收盘持仓。"
        "总长度尽量控制在 220 个中文字符以内，保持结论导向，不要编造数据。\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    return request_agent_text(ctx.config, prompt)
