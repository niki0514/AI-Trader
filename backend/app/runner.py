from __future__ import annotations

from typing import Any, Callable

from app.adapters.files import dump_stage_output
from app.components import (
    analyst,
    decider,
    executor,
    reporter,
    risk_guard,
    selector,
    update_holding_actions,
)
from app.pipeline import RunContext

Component = Callable[[RunContext, dict[str, Any]], dict[str, Any]]

PIPELINE_COMPONENTS: tuple[tuple[str, Component], ...] = (
    ("update_holding_actions", update_holding_actions.run),
    ("selector", selector.run),
    ("analyst", analyst.run),
    ("decider", decider.run),
    ("risk_guard", risk_guard.run),
    ("executor", executor.run),
    ("reporter", reporter.run),
)


def run_pipeline(ctx: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
    ctx.ensure_output_dirs()
    current_payload = dict(payload)
    for stage_index, (stage_name, component) in enumerate(PIPELINE_COMPONENTS, start=1):
        current_payload = component(ctx, current_payload)
        dump_stage_output(ctx, stage_name=stage_name, stage_index=stage_index, payload=current_payload)
    return current_payload
