from __future__ import annotations

from typing import Any

from app.adapters.files import dump_stage_output
from app.market_data import build_market_data_lookup, enrich_snapshot_with_market_data, summarize_market_data_context
from app.pipeline.artifacts import export_stage_artifacts
from app.pipeline.context import RunContext
from app.pipeline.results import StageResult
from app.pipeline.stages import (
    DEFAULT_STAGE_ORDER,
    STAGE_REGISTRY,
    build_stage_input_snapshot,
    build_pipeline_components,
    resolve_pipeline_stage_names,
    validate_artifact_updates,
    validate_stage_payload,
    validate_stage_updates,
    validate_pipeline_sequence,
)

PIPELINE_COMPONENTS: tuple[tuple[str, Any], ...] = build_pipeline_components(DEFAULT_STAGE_ORDER)


def run_pipeline(ctx: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
    ctx.ensure_output_dirs()
    current_payload = dict(payload)
    current_payload["trade_date"] = ctx.trade_date
    snapshot = payload.get("snapshot", {})
    if isinstance(snapshot, dict):
        enriched_snapshot = enrich_snapshot_with_market_data(snapshot=snapshot, config=ctx.config, trade_date=ctx.trade_date)
        current_payload["snapshot"] = snapshot
        current_payload["snapshot_market"] = enriched_snapshot
        current_payload["market_data_context"] = enriched_snapshot.get("market_data_context", {})
        current_payload["market_data_by_symbol"] = build_market_data_lookup(enriched_snapshot)
        stage_notes = dict(current_payload.get("stage_notes", {}))
        stage_notes["market_data"] = summarize_market_data_context(enriched_snapshot)
        current_payload["stage_notes"] = stage_notes
    stage_names = resolve_pipeline_stage_names(ctx.config, overrides=current_payload)
    current_payload["pipeline_stages"] = list(stage_names)
    validate_pipeline_sequence(stage_names, initial_payload=current_payload)

    stage_notes = dict(current_payload.get("stage_notes", {}))
    stage_notes["pipeline"] = ",".join(stage_names)
    current_payload["stage_notes"] = stage_notes

    pipeline_components = tuple((stage_name, STAGE_REGISTRY[stage_name].component) for stage_name in stage_names)
    for stage_index, (stage_name, component) in enumerate(pipeline_components, start=1):
        stage_inputs = build_stage_input_snapshot(stage_name, current_payload)
        validate_stage_payload(stage_name, current_payload)
        stage_result = component(ctx, current_payload)
        if not isinstance(stage_result, StageResult):
            raise TypeError(f"pipeline stage '{stage_name}' must return StageResult")
        validate_stage_updates(stage_name, stage_result.updates)
        artifact_updates = export_stage_artifacts(ctx, stage_name, stage_result.updates)
        validate_artifact_updates(stage_name, artifact_updates)
        current_payload = _merge_stage_updates(current_payload, stage_name=stage_name, updates=stage_result.updates, stage_note=stage_result.stage_note)
        current_payload = _merge_artifact_updates(current_payload, artifact_updates)
        dump_stage_output(
            ctx,
            stage_name=stage_name,
            stage_index=stage_index,
            payload=_build_stage_dump_payload(
                ctx=ctx,
                stage_index=stage_index,
                stage_name=stage_name,
                pipeline_stages=stage_names,
                stage_inputs=stage_inputs,
                stage_result=stage_result,
                artifact_updates=artifact_updates,
            ),
        )
    return current_payload


def _merge_stage_updates(
    payload: dict[str, Any],
    *,
    stage_name: str,
    updates: dict[str, Any],
    stage_note: str,
) -> dict[str, Any]:
    merged = dict(payload)
    merged.update(updates)

    if stage_note:
        notes = dict(merged.get("stage_notes", {}))
        notes[stage_name] = stage_note
        merged["stage_notes"] = notes
    return merged


def _merge_artifact_updates(payload: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    if not updates:
        return payload
    merged = dict(payload)
    merged.update(updates)
    return merged


def _build_stage_dump_payload(
    *,
    ctx: RunContext,
    stage_index: int,
    stage_name: str,
    pipeline_stages: tuple[str, ...],
    stage_inputs: dict[str, Any],
    stage_result: StageResult,
    artifact_updates: dict[str, Any],
) -> dict[str, Any]:
    stage = STAGE_REGISTRY[stage_name]
    return {
        "run_id": ctx.run_id,
        "trade_date": ctx.trade_date,
        "stage_index": stage_index,
        "stage_name": stage_name,
        "pipeline_stages": list(pipeline_stages),
        "requires": list(stage.requires),
        "provides": list(stage.provides),
        "stage_note": stage_result.stage_note,
        "inputs": stage_inputs,
        "outputs": dict(stage_result.updates),
        "artifacts": dict(artifact_updates),
    }
