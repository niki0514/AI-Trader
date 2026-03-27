from __future__ import annotations

from typing import Any, Callable

from app.adapters import write_csv, write_json, write_text
from app.contracts import (
    AI_INSIGHT_FIELDS,
    HOLDING_ACTION_FIELDS,
    NAV_FIELDS,
    ORDER_CANDIDATE_FIELDS,
    POSITION_FIELDS,
    SIM_FILL_FIELDS,
    TECH_CANDIDATE_FIELDS,
    TRADE_PLAN_FIELDS,
)
from app.pipeline.io import (
    AnalystArtifactView,
    DeciderArtifactView,
    ExecutorArtifactView,
    HoldingActionsArtifactView,
    ReporterArtifactView,
    RiskGuardArtifactView,
    SelectorArtifactView,
)

ArtifactExporter = Callable[[Any, dict[str, Any]], dict[str, Any]]


def export_stage_artifacts(ctx: Any, stage_name: str, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    exporter = STAGE_ARTIFACT_EXPORTERS.get(stage_name)
    if exporter is None:
        return {}

    return exporter(ctx, stage_outputs) or {}


def _export_holding_actions(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = HoldingActionsArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("holding_actions_t.csv"), view.holding_actions, HOLDING_ACTION_FIELDS)
    return {}


def _export_selector(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = SelectorArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("tech_candidates_t.csv"), view.tech_candidates, TECH_CANDIDATE_FIELDS)
    return {}


def _export_analyst(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = AnalystArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("ai_insights_t.csv"), view.ai_insights, AI_INSIGHT_FIELDS)
    return {}


def _export_decider(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = DeciderArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("orders_candidate_t.csv"), view.orders_candidate, ORDER_CANDIDATE_FIELDS)
    return {}


def _export_risk_guard(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = RiskGuardArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("trade_plan_t.csv"), view.trade_plan, TRADE_PLAN_FIELDS)
    return {}


def _export_executor(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = ExecutorArtifactView.from_stage_outputs(stage_outputs)
    write_csv(ctx.artifact_path("sim_fill_t.csv"), view.sim_fill, SIM_FILL_FIELDS)
    write_csv(ctx.artifact_path("positions_t.csv"), view.positions, POSITION_FIELDS)
    write_csv(ctx.artifact_path("nav_t.csv"), view.nav, NAV_FIELDS)
    return {}


def _export_reporter(ctx: Any, stage_outputs: dict[str, Any]) -> dict[str, Any]:
    view = ReporterArtifactView.from_stage_outputs(stage_outputs)
    metrics_path = ctx.artifact_path("metrics_t.json")
    risk_report_path = ctx.artifact_path("risk_report_t.md")

    write_json(metrics_path, view.metrics)
    write_text(risk_report_path, view.risk_report_markdown)

    return {
        "report_files": {
            "metrics_t.json": str(metrics_path),
            "risk_report_t.md": str(risk_report_path),
        }
    }


STAGE_ARTIFACT_EXPORTERS: dict[str, ArtifactExporter] = {
    "update_holding_actions": _export_holding_actions,
    "selector": _export_selector,
    "analyst": _export_analyst,
    "decider": _export_decider,
    "risk_guard": _export_risk_guard,
    "executor": _export_executor,
    "reporter": _export_reporter,
}
