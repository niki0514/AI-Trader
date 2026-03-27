from __future__ import annotations

from dataclasses import dataclass
from types import UnionType
from typing import Any, Callable, Union, get_args, get_origin

from app.components import (
    analyst,
    decider,
    executor,
    reporter,
    risk_guard,
    selector,
    update_holding_actions,
)
from app.pipeline.outputs import (
    AIInsightRow,
    AnalystStageOutput,
    DeciderStageOutput,
    ExecutorStageOutput,
    HoldingActionRow,
    HoldingReviewStageOutput,
    MetricsSummary,
    NavRow,
    NewsSearchView,
    OrderCandidateRow,
    PositionRow,
    PositionSnapshotRow,
    RiskEventRow,
    ReporterStageOutput,
    RowModel,
    RiskGuardStageOutput,
    SelectorStageOutput,
    SimFillRow,
    TechCandidateRow,
    TradePlanRow,
    StageOutputModel,
)
from app.pipeline.results import StageResult

Component = Callable[[Any, dict[str, Any]], StageResult]
InputValidator = Callable[[dict[str, Any]], None]
OutputValidator = Callable[[dict[str, Any]], None]

PREPARED_PAYLOAD_KEYS: tuple[str, ...] = (
    "trade_date",
    "stage_notes",
    "snapshot_market",
    "market_data_context",
    "market_data_by_symbol",
)


def _input_snapshot_keys(*keys: str) -> tuple[str, ...]:
    resolved: list[str] = []
    for key in keys:
        candidates = (key, *PREPARED_PAYLOAD_KEYS) if key == "snapshot" else (key,)
        for candidate in candidates:
            if candidate not in resolved:
                resolved.append(candidate)
    return tuple(resolved)


@dataclass(frozen=True)
class PipelineStage:
    name: str
    component: Component
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    description: str = ""
    input_validator: InputValidator | None = None
    output_validator: OutputValidator | None = None
    output_model: type[StageOutputModel] | None = None
    output_contract: dict[str, str] | None = None
    input_snapshot_keys: tuple[str, ...] = ()


STAGE_REGISTRY: dict[str, PipelineStage] = {
    "update_holding_actions": PipelineStage(
        name="update_holding_actions",
        component=update_holding_actions.run,
        requires=("snapshot",),
        provides=("account", "risk_mode", "positions_prev", "positions", "holding_actions"),
        description="Review current holdings and generate HOLD / REDUCE / EXIT actions.",
        input_validator=lambda payload: _validate_snapshot_stage_input(payload),
        output_validator=lambda updates: _validate_holding_review_stage_output(updates),
        output_model=HoldingReviewStageOutput,
        output_contract={
            "account": "dict",
            "risk_mode": "str",
            "positions_prev": "PositionSnapshotRow[]",
            "positions": "PositionSnapshotRow[]",
            "holding_actions": "HoldingActionRow[]",
        },
        input_snapshot_keys=_input_snapshot_keys("snapshot"),
    ),
    "selector": PipelineStage(
        name="selector",
        component=selector.run,
        requires=("snapshot",),
        provides=("tech_candidates", "selector_watchlist", "selector_source", "stock_screen_result", "selector_failed"),
        description="Build candidate rows from watchlist or upstream stock screen.",
        input_validator=lambda payload: _validate_snapshot_stage_input(payload),
        output_validator=lambda updates: _validate_selector_stage_output(updates),
        output_model=SelectorStageOutput,
        output_contract={
            "tech_candidates": "TechCandidateRow[]",
            "selector_watchlist": "dict[]",
            "selector_source": "str",
            "stock_screen_result": "dict",
            "selector_failed": "bool",
        },
        input_snapshot_keys=_input_snapshot_keys("snapshot"),
    ),
    "analyst": PipelineStage(
        name="analyst",
        component=analyst.run,
        requires=("tech_candidates",),
        provides=("ai_insights", "analyst_news_search"),
        description="Generate AI insights for candidate symbols.",
        input_validator=lambda payload: _require_rows_field(payload, "tech_candidates", "analyst"),
        output_validator=lambda updates: _validate_analyst_stage_output(updates),
        output_model=AnalystStageOutput,
        output_contract={
            "ai_insights": "AIInsightRow[]",
            "analyst_news_search": "NewsSearchViewMap",
        },
        input_snapshot_keys=_input_snapshot_keys(
            "snapshot",
            "account",
            "positions_prev",
            "risk_mode",
            "tech_candidates",
            "selector_source",
            "selector_watchlist",
        ),
    ),
    "decider": PipelineStage(
        name="decider",
        component=decider.run,
        requires=("holding_actions", "ai_insights"),
        provides=("orders_candidate",),
        description="Merge holding actions and AI insights into order candidates.",
        input_validator=lambda payload: _validate_decider_stage_input(payload),
        output_validator=lambda updates: _require_rows_field(updates, "orders_candidate", "decider_output"),
        output_model=DeciderStageOutput,
        output_contract={
            "orders_candidate": "OrderCandidateRow[]",
        },
        input_snapshot_keys=_input_snapshot_keys(
            "snapshot",
            "account",
            "positions_prev",
            "risk_mode",
            "holding_actions",
            "ai_insights",
            "selector_watchlist",
        ),
    ),
    "risk_guard": PipelineStage(
        name="risk_guard",
        component=risk_guard.run,
        requires=("orders_candidate", "account", "positions_prev"),
        provides=("trade_plan", "risk_events", "risk_guard_failed"),
        description="Apply portfolio and market risk constraints to order candidates.",
        input_validator=lambda payload: _validate_risk_guard_stage_input(payload),
        output_validator=lambda updates: _validate_risk_guard_stage_output(updates),
        output_model=RiskGuardStageOutput,
        output_contract={
            "trade_plan": "TradePlanRow[]",
            "risk_events": "RiskEventRow[]",
            "risk_guard_failed": "bool",
        },
        input_snapshot_keys=_input_snapshot_keys(
            "account",
            "positions_prev",
            "risk_mode",
            "orders_candidate",
            "tech_candidates",
        ),
    ),
    "executor": PipelineStage(
        name="executor",
        component=executor.run,
        requires=("trade_plan", "account", "positions_prev"),
        provides=("sim_fill", "positions", "nav", "executor_failed"),
        description="Simulate fills and update positions and NAV.",
        input_validator=lambda payload: _validate_executor_stage_input(payload),
        output_validator=lambda updates: _validate_executor_stage_output(updates),
        output_model=ExecutorStageOutput,
        output_contract={
            "sim_fill": "SimFillRow[]",
            "positions": "PositionRow[]",
            "nav": "NavRow[]",
            "executor_failed": "bool",
        },
        input_snapshot_keys=_input_snapshot_keys(
            "snapshot",
            "account",
            "positions_prev",
            "risk_mode",
            "trade_plan",
            "selector_watchlist",
        ),
    ),
    "reporter": PipelineStage(
        name="reporter",
        component=reporter.run,
        requires=("trade_plan", "sim_fill", "nav"),
        provides=("metrics", "risk_report_markdown"),
        description="Generate metrics and end-of-day markdown report.",
        input_validator=lambda payload: _validate_reporter_stage_input(payload),
        output_validator=lambda updates: _validate_reporter_stage_output(updates),
        output_model=ReporterStageOutput,
        output_contract={
            "metrics": "MetricsSummary",
            "risk_report_markdown": "str",
        },
        input_snapshot_keys=_input_snapshot_keys(
            "snapshot",
            "account",
            "positions_prev",
            "risk_mode",
            "trade_plan",
            "sim_fill",
            "positions",
            "nav",
            "risk_events",
            "selector_failed",
            "stage_notes",
            "run_id",
        ),
    ),
}

DEFAULT_STAGE_ORDER: tuple[str, ...] = (
    "update_holding_actions",
    "selector",
    "analyst",
    "decider",
    "risk_guard",
    "executor",
    "reporter",
)

PIPELINE_PRESETS: dict[str, tuple[str, ...]] = {
    "full": DEFAULT_STAGE_ORDER,
    "holding_review": ("update_holding_actions",),
    "research": ("selector", "analyst"),
    "decision": ("update_holding_actions", "selector", "analyst", "decider"),
    "planning": ("update_holding_actions", "selector", "analyst", "decider", "risk_guard"),
    "execution": ("executor", "reporter"),
}

RUNTIME_MANAGED_OUTPUTS: tuple[str, ...] = ("stage_notes",)

ARTIFACT_MANAGED_OUTPUTS: dict[str, tuple[str, ...]] = {
    "reporter": ("report_files",),
}


def build_pipeline_components(stage_names: tuple[str, ...]) -> tuple[tuple[str, Component], ...]:
    return tuple((stage_name, STAGE_REGISTRY[stage_name].component) for stage_name in stage_names)


def resolve_pipeline_stage_names(config: dict[str, Any], overrides: dict[str, Any] | None = None) -> tuple[str, ...]:
    pipeline_config = config.get("pipeline", {})
    overrides = overrides or {}

    override_stages = _coerce_stage_names(overrides.get("pipeline_stages"))
    if override_stages:
        return _validate_stage_names(override_stages)

    configured_stages = _coerce_stage_names(pipeline_config.get("stages"))
    if configured_stages:
        return _validate_stage_names(configured_stages)

    preset_name = (
        str(
            overrides.get("pipeline_preset")
            or pipeline_config.get("preset")
            or "full"
        )
        .strip()
        .lower()
    )
    if not preset_name:
        preset_name = "full"
    if preset_name not in PIPELINE_PRESETS:
        available = ", ".join(sorted(PIPELINE_PRESETS))
        raise ValueError(f"unknown pipeline preset: {preset_name}; available presets: {available}")
    return PIPELINE_PRESETS[preset_name]


def validate_pipeline_sequence(stage_names: tuple[str, ...], initial_payload: dict[str, Any]) -> None:
    available = set(initial_payload.keys())
    if "snapshot" in available:
        available.update(PREPARED_PAYLOAD_KEYS)

    for stage_name in stage_names:
        stage = STAGE_REGISTRY[stage_name]
        missing = [key for key in stage.requires if key not in available]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"pipeline stage '{stage_name}' missing required inputs: {joined}")
        available.update(stage.provides)


def list_stage_names() -> tuple[str, ...]:
    return tuple(STAGE_REGISTRY.keys())


def list_pipeline_presets() -> dict[str, tuple[str, ...]]:
    return dict(PIPELINE_PRESETS)


def build_pipeline_catalog() -> dict[str, Any]:
    return {
        "default_stage_order": list(DEFAULT_STAGE_ORDER),
        "presets": {name: list(stage_names) for name, stage_names in PIPELINE_PRESETS.items()},
        "prepared_payload_keys": list(PREPARED_PAYLOAD_KEYS),
        "runtime_managed_outputs": list(RUNTIME_MANAGED_OUTPUTS),
        "artifact_managed_outputs": {stage_name: list(keys) for stage_name, keys in ARTIFACT_MANAGED_OUTPUTS.items()},
        "stages": {
            stage_name: {
                "requires": list(stage.requires),
                "provides": list(stage.provides),
                "artifact_outputs": list(ARTIFACT_MANAGED_OUTPUTS.get(stage_name, ())),
                "output_model": stage.output_model.__name__ if stage.output_model is not None else "",
                "output_contract": dict(stage.output_contract or {}),
                "input_snapshot_keys": list(stage.input_snapshot_keys),
                "description": stage.description,
            }
            for stage_name, stage in STAGE_REGISTRY.items()
        },
    }


def validate_stage_updates(stage_name: str, updates: dict[str, Any]) -> None:
    stage = STAGE_REGISTRY[stage_name]
    unexpected = sorted(set(updates) - set(stage.provides))
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"pipeline stage '{stage_name}' produced undeclared outputs: {joined}")
    validator = stage.output_validator
    if validator is not None:
        validator(updates)


def validate_stage_payload(stage_name: str, payload: dict[str, Any]) -> None:
    validator = STAGE_REGISTRY[stage_name].input_validator
    if validator is None:
        return
    validator(payload)


def validate_artifact_updates(stage_name: str, updates: dict[str, Any]) -> None:
    allowed = set(ARTIFACT_MANAGED_OUTPUTS.get(stage_name, ()))
    unexpected = sorted(set(updates) - allowed)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"artifact exporter for stage '{stage_name}' produced undeclared outputs: {joined}")
    _validate_artifact_output_shape(stage_name, updates)


def build_stage_input_snapshot(stage_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    stage = STAGE_REGISTRY[stage_name]
    snapshot: dict[str, Any] = {}
    for key in stage.input_snapshot_keys:
        if key in payload:
            snapshot[key] = payload[key]
    return snapshot


def _validate_snapshot_stage_input(payload: dict[str, Any]) -> None:
    _require_mapping_field(payload, "snapshot", "snapshot_stage")


def _validate_decider_stage_input(payload: dict[str, Any]) -> None:
    _require_model_rows_field(payload, "holding_actions", "decider", HoldingActionRow)
    _require_model_rows_field(payload, "ai_insights", "decider", AIInsightRow)


def _validate_risk_guard_stage_input(payload: dict[str, Any]) -> None:
    _require_model_rows_field(payload, "orders_candidate", "risk_guard", OrderCandidateRow)
    _require_account_field(payload, "account", "risk_guard")
    _require_model_rows_field(payload, "positions_prev", "risk_guard", PositionSnapshotRow)


def _validate_executor_stage_input(payload: dict[str, Any]) -> None:
    _require_model_rows_field(payload, "trade_plan", "executor", TradePlanRow)
    _require_account_field(payload, "account", "executor")
    _require_model_rows_field(payload, "positions_prev", "executor", PositionSnapshotRow)


def _validate_reporter_stage_input(payload: dict[str, Any]) -> None:
    _require_model_rows_field(payload, "trade_plan", "reporter", TradePlanRow)
    _require_model_rows_field(payload, "sim_fill", "reporter", SimFillRow)
    _require_model_rows_field(payload, "nav", "reporter", NavRow)


def _validate_holding_review_stage_output(updates: dict[str, Any]) -> None:
    _require_account_field(updates, "account", "update_holding_actions_output")
    _require_string_field(updates, "risk_mode", "update_holding_actions_output")
    _require_model_rows_field(updates, "positions_prev", "update_holding_actions_output", PositionSnapshotRow)
    _require_model_rows_field(updates, "positions", "update_holding_actions_output", PositionSnapshotRow)
    _require_model_rows_field(updates, "holding_actions", "update_holding_actions_output", HoldingActionRow)


def _validate_selector_stage_output(updates: dict[str, Any]) -> None:
    _require_model_rows_field(updates, "tech_candidates", "selector_output", TechCandidateRow)
    _require_symbol_rows_field(updates, "selector_watchlist", "selector_output")
    _require_string_field(updates, "selector_source", "selector_output")
    _require_mapping_field(updates, "stock_screen_result", "selector_output")
    _require_boolean_field(updates, "selector_failed", "selector_output")


def _validate_analyst_stage_output(updates: dict[str, Any]) -> None:
    _require_model_rows_field(updates, "ai_insights", "analyst_output", AIInsightRow)
    _require_model_mapping_field(updates, "analyst_news_search", "analyst_output", NewsSearchView)


def _validate_risk_guard_stage_output(updates: dict[str, Any]) -> None:
    _require_model_rows_field(updates, "trade_plan", "risk_guard_output", TradePlanRow)
    _require_model_rows_field(updates, "risk_events", "risk_guard_output", RiskEventRow)
    _require_boolean_field(updates, "risk_guard_failed", "risk_guard_output")


def _validate_executor_stage_output(updates: dict[str, Any]) -> None:
    _require_model_rows_field(updates, "sim_fill", "executor_output", SimFillRow)
    _require_model_rows_field(updates, "positions", "executor_output", PositionRow)
    _require_model_rows_field(updates, "nav", "executor_output", NavRow)
    _require_boolean_field(updates, "executor_failed", "executor_output")


def _validate_reporter_stage_output(updates: dict[str, Any]) -> None:
    _require_model_field(updates, "metrics", "reporter_output", MetricsSummary)
    _require_string_field(updates, "risk_report_markdown", "reporter_output")


def _validate_artifact_output_shape(stage_name: str, updates: dict[str, Any]) -> None:
    if stage_name == "reporter" and updates:
        _require_mapping_field(updates, "report_files", "reporter_artifact")


def _require_mapping_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"pipeline stage '{stage_name}' expects '{key}' to be an object")


def _require_rows_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"pipeline stage '{stage_name}' expects '{key}' to be an array")


def _require_string_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"pipeline stage '{stage_name}' expects '{key}' to be a string")


def _require_boolean_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"pipeline stage '{stage_name}' expects '{key}' to be a boolean")


def _require_account_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    _require_mapping_field(payload, key, stage_name)
    required_keys = ("cash", "total_equity", "prev_total_equity", "initial_equity", "portfolio_drawdown_pct")
    _require_mapping_keys(dict(payload.get(key, {})), key=key, stage_name=stage_name, required_keys=required_keys)


def _require_symbol_rows_field(payload: dict[str, Any], key: str, stage_name: str) -> None:
    _require_rows_field(payload, key, stage_name)
    rows = payload.get(key, [])
    for index, row in enumerate(rows):
        context = f"{key}[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an object")
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}.symbol' to be a non-empty string")


def _require_model_field(
    payload: dict[str, Any],
    key: str,
    stage_name: str,
    model_type: type[RowModel],
) -> None:
    value = payload.get(key)
    _validate_row_model_payload(
        value,
        model_type=model_type,
        stage_name=stage_name,
        context=key,
    )


def _require_model_rows_field(
    payload: dict[str, Any],
    key: str,
    stage_name: str,
    model_type: type[RowModel],
) -> None:
    _require_rows_field(payload, key, stage_name)
    rows = payload.get(key, [])
    for index, row in enumerate(rows):
        _validate_row_model_payload(
            row,
            model_type=model_type,
            stage_name=stage_name,
            context=f"{key}[{index}]",
        )


def _require_model_mapping_field(
    payload: dict[str, Any],
    key: str,
    stage_name: str,
    model_type: type[RowModel],
) -> None:
    _require_mapping_field(payload, key, stage_name)
    mapping = dict(payload.get(key, {}))
    for mapping_key, value in mapping.items():
        if not isinstance(mapping_key, str) or not mapping_key.strip():
            raise ValueError(f"pipeline stage '{stage_name}' expects '{key}' to use non-empty string keys")
        _validate_row_model_payload(
            value,
            model_type=model_type,
            stage_name=stage_name,
            context=f"{key}[{mapping_key!r}]",
        )


def _validate_row_model_payload(
    value: Any,
    *,
    model_type: type[RowModel],
    stage_name: str,
    context: str,
) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an object")

    expected_keys = set(model_type.field_names())
    actual_keys = set(value.keys())
    missing = sorted(expected_keys - actual_keys)
    if missing:
        raise ValueError(
            f"pipeline stage '{stage_name}' expects '{context}' to include keys: {', '.join(missing)}"
        )
    unexpected = sorted(actual_keys - expected_keys)
    if unexpected:
        raise ValueError(
            f"pipeline stage '{stage_name}' expects '{context}' to only include declared keys; got: {', '.join(unexpected)}"
        )

    for field_name, field_type in model_type.field_types().items():
        _validate_typed_value(
            value[field_name],
            expected_type=field_type,
            stage_name=stage_name,
            context=f"{context}.{field_name}",
        )


def _validate_typed_value(
    value: Any,
    *,
    expected_type: Any,
    stage_name: str,
    context: str,
) -> None:
    if expected_type is Any:
        return

    origin = get_origin(expected_type)
    if origin in {list, tuple}:
        if not isinstance(value, list):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an array")
        item_types = get_args(expected_type)
        item_type = item_types[0] if item_types else Any
        for index, item in enumerate(value):
            _validate_typed_value(
                item,
                expected_type=item_type,
                stage_name=stage_name,
                context=f"{context}[{index}]",
            )
        return

    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an object")
        key_type, value_type = get_args(expected_type) if get_args(expected_type) else (Any, Any)
        for mapping_key, mapping_value in value.items():
            if key_type is str and not isinstance(mapping_key, str):
                raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to use string keys")
            _validate_typed_value(
                mapping_value,
                expected_type=value_type,
                stage_name=stage_name,
                context=f"{context}[{mapping_key!r}]",
            )
        return

    if origin in {UnionType, Union}:
        union_types = get_args(expected_type)
        if value is None and type(None) in union_types:
            return
        for union_type in union_types:
            if union_type is type(None):
                continue
            try:
                _validate_typed_value(
                    value,
                    expected_type=union_type,
                    stage_name=stage_name,
                    context=context,
                )
                return
            except ValueError:
                continue
        raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to match declared schema")

    if isinstance(expected_type, type) and issubclass(expected_type, RowModel):
        _validate_row_model_payload(value, model_type=expected_type, stage_name=stage_name, context=context)
        return

    if expected_type is str:
        if not isinstance(value, str):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be a string")
        return

    if expected_type is bool:
        if not isinstance(value, bool):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be a boolean")
        return

    if expected_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an integer")
        return

    if expected_type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be a number")
        return

    if expected_type is dict:
        if not isinstance(value, dict):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an object")
        return

    if expected_type is list:
        if not isinstance(value, list):
            raise ValueError(f"pipeline stage '{stage_name}' expects '{context}' to be an array")
        return


def _require_mapping_keys(
    value: dict[str, Any],
    *,
    key: str,
    stage_name: str,
    required_keys: tuple[str, ...],
) -> None:
    missing = [required_key for required_key in required_keys if required_key not in value]
    if missing:
        raise ValueError(
            f"pipeline stage '{stage_name}' expects '{key}' to include keys: {', '.join(missing)}"
        )


def _validate_stage_names(stage_names: tuple[str, ...]) -> tuple[str, ...]:
    unknown = [stage_name for stage_name in stage_names if stage_name not in STAGE_REGISTRY]
    if unknown:
        available = ", ".join(list_stage_names())
        raise ValueError(f"unknown pipeline stages: {', '.join(unknown)}; available stages: {available}")
    return stage_names


def _coerce_stage_names(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) and not value.strip():
        return ()
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value]
        return tuple(item for item in parts if item)
    raise ValueError("pipeline stages must be an array")
