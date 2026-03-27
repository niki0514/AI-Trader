from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.adapters import read_json


@dataclass(frozen=True)
class SnapshotInput:
    snapshot: dict[str, Any]
    input_path: Path
    input_label: str


@dataclass(frozen=True)
class RunDailyJobRequest:
    config_path: Path
    output_root: Path
    snapshot_input: SnapshotInput
    trade_date: str
    run_id: str
    pipeline_preset: str
    pipeline_stages: list[str]

    @classmethod
    def from_body(
        cls,
        body: dict[str, Any],
        *,
        backend_dir: Path,
        default_config_path: Path,
        default_input_path: Path,
        default_output_root: Path,
    ) -> RunDailyJobRequest:
        snapshot_input = _resolve_snapshot_input(
            body,
            backend_dir=backend_dir,
            default_input_path=default_input_path,
        )
        trade_date = str(body.get("trade_date") or snapshot_input.snapshot.get("trade_date") or _today()).strip()
        return cls(
            config_path=_resolve_path(body.get("config_file"), default_config_path),
            output_root=_resolve_path(body.get("output_root"), default_output_root),
            snapshot_input=snapshot_input,
            trade_date=trade_date,
            run_id=_optional_string(body.get("run_id")),
            pipeline_preset=_optional_string(body.get("pipeline_preset")),
            pipeline_stages=_parse_string_array(body.get("pipeline_stages"), field_name="pipeline_stages"),
        )


@dataclass(frozen=True)
class StockScreenQueryRequest:
    config_path: Path
    output_root: Path
    export_root: Path
    keyword: str
    market: str
    request_id: str
    include_rows: bool
    preview_limit: int
    page_no: int
    page_size: int | None
    fetch_all: bool | None

    @classmethod
    def from_body(
        cls,
        body: dict[str, Any],
        *,
        default_config_path: Path,
        default_output_root: Path,
    ) -> StockScreenQueryRequest:
        output_root = _resolve_path(body.get("output_root"), default_output_root)
        keyword = _required_string(body.get("keyword"), field_name="keyword")
        return cls(
            config_path=_resolve_path(body.get("config_file"), default_config_path),
            output_root=output_root,
            export_root=_resolve_path(body.get("export_root"), output_root / "stock_screen"),
            keyword=keyword,
            market=_optional_string(body.get("market")),
            request_id=_optional_string(body.get("request_id")),
            include_rows=_parse_bool(body.get("include_rows"), field_name="include_rows", default=False),
            preview_limit=_parse_positive_int(body.get("preview_limit"), field_name="preview_limit", default=20),
            page_no=_parse_positive_int(body.get("page_no"), field_name="page_no", default=1),
            page_size=_parse_optional_positive_int(body.get("page_size"), field_name="page_size"),
            fetch_all=_parse_optional_bool(body.get("fetch_all"), field_name="fetch_all"),
        )


@dataclass(frozen=True)
class NewsSearchQueryRequest:
    config_path: Path
    output_root: Path
    export_root: Path
    query: str
    request_id: str
    include_items: bool
    preview_limit: int
    excerpt_chars: int
    size: int | None
    start_date: str
    end_date: str
    child_search_type: str

    @classmethod
    def from_body(
        cls,
        body: dict[str, Any],
        *,
        default_config_path: Path,
        default_output_root: Path,
    ) -> NewsSearchQueryRequest:
        output_root = _resolve_path(body.get("output_root"), default_output_root)
        query = _required_string(body.get("query"), field_name="query")
        return cls(
            config_path=_resolve_path(body.get("config_file"), default_config_path),
            output_root=output_root,
            export_root=_resolve_path(body.get("export_root"), output_root / "news_search"),
            query=query,
            request_id=_optional_string(body.get("request_id")),
            include_items=_parse_bool(body.get("include_items"), field_name="include_items", default=False),
            preview_limit=_parse_positive_int(body.get("preview_limit"), field_name="preview_limit", default=6),
            excerpt_chars=_parse_positive_int(body.get("excerpt_chars"), field_name="excerpt_chars", default=240),
            size=_parse_optional_positive_int(body.get("size"), field_name="size"),
            start_date=_optional_string(body.get("start_date")),
            end_date=_optional_string(body.get("end_date")),
            child_search_type=_optional_string(body.get("child_search_type")),
        )


def _resolve_snapshot_input(
    body: dict[str, Any],
    *,
    backend_dir: Path,
    default_input_path: Path,
) -> SnapshotInput:
    inline_snapshot = body.get("snapshot")
    if inline_snapshot is not None:
        if not isinstance(inline_snapshot, dict):
            raise ValueError("snapshot must be an object")
        input_path = backend_dir / "inline_snapshot.json"
        return SnapshotInput(snapshot=dict(inline_snapshot), input_path=input_path, input_label="<inline_snapshot>")

    input_path = _resolve_path(body.get("input_file"), default_input_path)
    snapshot = read_json(input_path)
    return SnapshotInput(snapshot=snapshot, input_path=input_path, input_label=str(input_path))


def _resolve_path(value: Any, default_path: Path) -> Path:
    if value in {"", None}:
        return default_path.resolve()
    return Path(str(value)).resolve()


def _required_string(value: Any, *, field_name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_string(value: Any) -> str:
    if value in {"", None}:
        return ""
    return str(value).strip()


def _parse_string_array(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    items = [str(item).strip() for item in value]
    result = [item for item in items if item]
    if not result:
        raise ValueError(f"{field_name} must include at least one stage")
    return result


def _parse_positive_int(value: Any, *, field_name: str, default: int) -> int:
    if value in {"", None}:
        return default
    parsed = _parse_int(value, field_name=field_name)
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return parsed


def _parse_optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value in {"", None}:
        return None
    parsed = _parse_int(value, field_name=field_name)
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return parsed


def _parse_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    return parsed


def _parse_bool(value: Any, *, field_name: str, default: bool) -> bool:
    parsed = _parse_optional_bool(value, field_name=field_name)
    if parsed is None:
        return default
    return parsed


def _parse_optional_bool(value: Any, *, field_name: str) -> bool | None:
    if value in {"", None}:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{field_name} must be a boolean")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
