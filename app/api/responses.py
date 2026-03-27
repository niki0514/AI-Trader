from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any

from app.pipeline.outputs import RowModel


class ApiResponseModel:
    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in fields(self):
            serialized = _serialize_value(getattr(self, field.name))
            if serialized is not None:
                payload[field.name] = serialized
        return payload


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, ApiResponseModel):
        return value.to_dict()
    if isinstance(value, RowModel):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        serialized: dict[str, Any] = {}
        for key, item in value.items():
            converted = _serialize_value(item)
            if converted is not None:
                serialized[str(key)] = converted
        return serialized
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if is_dataclass(value):
        return {
            field.name: _serialize_value(getattr(value, field.name))
            for field in fields(value)
            if _serialize_value(getattr(value, field.name)) is not None
        }
    return value


@dataclass(frozen=True)
class ErrorResponse(ApiResponseModel):
    error: str


@dataclass(frozen=True)
class HealthResponse(ApiResponseModel):
    status: str = "ok"


@dataclass(frozen=True)
class RunDailyJobResponse(ApiResponseModel):
    job_id: str
    status: str
    mode: str
    run_id: str
    trade_date: str
    output_dir: str
    pipeline_stages: list[str]
    stage_notes: dict[str, Any]
    metrics: dict[str, Any]
    artifacts: dict[str, str]

    @classmethod
    def from_result(
        cls,
        *,
        run_id: str,
        trade_date: str,
        output_dir: Path,
        result: dict[str, Any],
    ) -> RunDailyJobResponse:
        return cls(
            job_id=run_id,
            status="completed",
            mode="sync",
            run_id=run_id,
            trade_date=trade_date,
            output_dir=str(output_dir),
            pipeline_stages=[str(item) for item in list(result.get("pipeline_stages", []))],
            stage_notes=dict(result.get("stage_notes", {})),
            metrics=dict(result.get("metrics", {})),
            artifacts={str(key): str(value) for key, value in dict(result.get("report_files", {})).items()},
        )


@dataclass(frozen=True)
class StockScreenQueryResponse(ApiResponseModel):
    request_id: str
    keyword: str
    effective_keyword: str
    market: str
    status: int
    message: str
    business_code: str
    business_msg: str
    result_type: int
    total: int
    row_count: int
    page_size: int
    pages_fetched: int
    fetch_all: bool
    parser_text: str
    response_conditions: list[dict[str, Any]]
    total_condition: dict[str, Any]
    columns: list[dict[str, Any]]
    preview_rows: list[dict[str, Any]]
    preview_count: int
    rows: list[dict[str, Any]] | None
    artifacts: dict[str, str]

    @classmethod
    def from_result(
        cls,
        *,
        result: dict[str, Any],
        preview_limit: int,
        include_rows: bool,
    ) -> StockScreenQueryResponse:
        rows = list(result.get("rows", []))
        preview_rows = [dict(item) for item in rows[:preview_limit]]
        return cls(
            request_id=str(result.get("request_id") or ""),
            keyword=str(result.get("keyword") or ""),
            effective_keyword=str(result.get("effective_keyword") or ""),
            market=str(result.get("market") or ""),
            status=int(result.get("status") or 0),
            message=str(result.get("message") or ""),
            business_code=str(result.get("business_code") or ""),
            business_msg=str(result.get("business_msg") or ""),
            result_type=int(result.get("result_type") or 0),
            total=int(result.get("total") or 0),
            row_count=int(result.get("row_count") or len(rows)),
            page_size=int(result.get("page_size") or 0),
            pages_fetched=int(result.get("pages_fetched") or 0),
            fetch_all=bool(result.get("fetch_all", False)),
            parser_text=str(result.get("parser_text") or ""),
            response_conditions=[dict(item) for item in list(result.get("response_conditions", [])) if isinstance(item, dict)],
            total_condition=dict(result.get("total_condition", {})),
            columns=[dict(item) for item in list(result.get("columns", [])) if isinstance(item, dict)],
            preview_rows=preview_rows,
            preview_count=min(len(rows), preview_limit),
            rows=[dict(item) for item in rows] if include_rows else None,
            artifacts={str(key): str(value) for key, value in dict(result.get("artifacts", {})).items()},
        )


@dataclass(frozen=True)
class NewsPreviewItem(ApiResponseModel):
    index: int | None
    title: str
    date: str
    information_type: str
    attach_type: str
    jump_url: str
    trunk_excerpt: str

    @classmethod
    def from_item(cls, item: dict[str, Any], *, excerpt_chars: int) -> NewsPreviewItem:
        trunk = str(item.get("trunk") or "").strip()
        if len(trunk) > excerpt_chars:
            trunk = trunk[: max(excerpt_chars - 1, 0)].rstrip() + "…"
        index_value = item.get("index")
        index = index_value if isinstance(index_value, int) and not isinstance(index_value, bool) else None
        return cls(
            index=index,
            title=str(item.get("title") or ""),
            date=str(item.get("date") or ""),
            information_type=str(item.get("information_type") or ""),
            attach_type=str(item.get("attach_type") or ""),
            jump_url=str(item.get("jump_url") or ""),
            trunk_excerpt=trunk,
        )


@dataclass(frozen=True)
class NewsSearchQueryResponse(ApiResponseModel):
    request_id: str
    query: str
    status: int
    message: str
    business_status: int
    business_code: int
    business_message: str
    search_status: int
    search_code: int
    search_message: str
    protocol_type: str
    trace_id: str
    search_id: str
    count: int
    request: dict[str, Any]
    extra_infos: dict[str, Any]
    preview_items: list[NewsPreviewItem]
    preview_count: int
    items: list[dict[str, Any]] | None
    artifacts: dict[str, str]

    @classmethod
    def from_result(
        cls,
        *,
        result: dict[str, Any],
        preview_limit: int,
        excerpt_chars: int,
        include_items: bool,
    ) -> NewsSearchQueryResponse:
        items = [dict(item) for item in list(result.get("items", [])) if isinstance(item, dict)]
        return cls(
            request_id=str(result.get("request_id") or ""),
            query=str(result.get("query") or ""),
            status=int(result.get("status") or 0),
            message=str(result.get("message") or ""),
            business_status=int(result.get("business_status") or 0),
            business_code=int(result.get("business_code") or 0),
            business_message=str(result.get("business_message") or ""),
            search_status=int(result.get("search_status") or 0),
            search_code=int(result.get("search_code") or 0),
            search_message=str(result.get("search_message") or ""),
            protocol_type=str(result.get("protocol_type") or ""),
            trace_id=str(result.get("trace_id") or ""),
            search_id=str(result.get("search_id") or ""),
            count=int(result.get("count") or len(items)),
            request=dict(result.get("request", {})),
            extra_infos=dict(result.get("extra_infos", {})),
            preview_items=[NewsPreviewItem.from_item(item, excerpt_chars=excerpt_chars) for item in items[:preview_limit]],
            preview_count=min(len(items), preview_limit),
            items=items if include_items else None,
            artifacts={str(key): str(value) for key, value in dict(result.get("artifacts", {})).items()},
        )


@dataclass(frozen=True)
class PositionsLatestResponse(ApiResponseModel):
    trade_date: str
    run_id: str
    source: str
    output_dir: str
    count: int
    positions: list[dict[str, Any]]


@dataclass(frozen=True)
class PlansByDateResponse(ApiResponseModel):
    trade_date: str
    run_id: str
    source: str
    output_dir: str
    count: int
    plans: list[dict[str, Any]]


@dataclass(frozen=True)
class FillsByDateResponse(ApiResponseModel):
    trade_date: str
    run_id: str
    source: str
    output_dir: str
    count: int
    fills: list[dict[str, Any]]


@dataclass(frozen=True)
class NavRangeResponse(ApiResponseModel):
    start: str
    end: str
    count: int
    nav: list[dict[str, Any]]


@dataclass(frozen=True)
class DailyReportResponse(ApiResponseModel):
    trade_date: str
    run_id: str
    source: str
    output_dir: str
    metrics: dict[str, Any]
    risk_report_markdown: str


@dataclass(frozen=True)
class PipelineStageCatalogEntry(ApiResponseModel):
    requires: list[str]
    provides: list[str]
    artifact_outputs: list[str]
    output_model: str
    output_contract: dict[str, str]
    input_snapshot_keys: list[str]
    description: str


@dataclass(frozen=True)
class PipelineCatalogResponse(ApiResponseModel):
    default_stage_order: list[str]
    presets: dict[str, list[str]]
    prepared_payload_keys: list[str]
    runtime_managed_outputs: list[str]
    artifact_managed_outputs: dict[str, list[str]]
    stages: dict[str, PipelineStageCatalogEntry]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PipelineCatalogResponse:
        stage_entries: dict[str, PipelineStageCatalogEntry] = {}
        for stage_name, stage_payload in dict(payload.get("stages", {})).items():
            stage_data = dict(stage_payload) if isinstance(stage_payload, dict) else {}
            stage_entries[str(stage_name)] = PipelineStageCatalogEntry(
                requires=_string_list(stage_data.get("requires")),
                provides=_string_list(stage_data.get("provides")),
                artifact_outputs=_string_list(stage_data.get("artifact_outputs")),
                output_model=str(stage_data.get("output_model") or ""),
                output_contract=_string_mapping(stage_data.get("output_contract")),
                input_snapshot_keys=_string_list(stage_data.get("input_snapshot_keys")),
                description=str(stage_data.get("description") or ""),
            )

        return cls(
            default_stage_order=_string_list(payload.get("default_stage_order")),
            presets=_string_list_mapping(payload.get("presets")),
            prepared_payload_keys=_string_list(payload.get("prepared_payload_keys")),
            runtime_managed_outputs=_string_list(payload.get("runtime_managed_outputs")),
            artifact_managed_outputs=_string_list_mapping(payload.get("artifact_managed_outputs")),
            stages=stage_entries,
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _string_list_mapping(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _string_list(item) for key, item in value.items()}


__all__ = [
    "ApiResponseModel",
    "DailyReportResponse",
    "ErrorResponse",
    "FillsByDateResponse",
    "HealthResponse",
    "NavRangeResponse",
    "NewsPreviewItem",
    "NewsSearchQueryResponse",
    "PipelineCatalogResponse",
    "PipelineStageCatalogEntry",
    "PlansByDateResponse",
    "PositionsLatestResponse",
    "RunDailyJobResponse",
    "StockScreenQueryResponse",
]
