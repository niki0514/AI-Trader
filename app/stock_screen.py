from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters import write_csv, write_json
from app.utils import to_bool, to_int


DEFAULT_STOCK_SCREEN_ENDPOINT = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"
SUPPORTED_MARKETS = {"A股", "港股", "美股"}
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 200
DEFAULT_TIMEOUT_SECONDS = 20
REQUEST_ID_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

PageRequestFn = Callable[[dict[str, Any], "StockScreenSettings", str], dict[str, Any]]


class StockScreenError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StockScreenSettings:
    endpoint: str
    api_key_env: str
    timeout_seconds: int
    default_page_size: int
    fetch_all_pages: bool
    max_pages: int


def load_stock_screen_settings(config: dict[str, Any]) -> StockScreenSettings:
    stock_screen_config = config.get("stock_screen", {})
    return StockScreenSettings(
        endpoint=str(stock_screen_config.get("endpoint") or DEFAULT_STOCK_SCREEN_ENDPOINT),
        api_key_env=str(stock_screen_config.get("api_key_env") or "MX_APIKEY"),
        timeout_seconds=max(to_int(stock_screen_config.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS), 1),
        default_page_size=max(to_int(stock_screen_config.get("default_page_size"), DEFAULT_PAGE_SIZE), 1),
        fetch_all_pages=to_bool(stock_screen_config.get("fetch_all_pages"), True),
        max_pages=max(to_int(stock_screen_config.get("max_pages"), DEFAULT_MAX_PAGES), 1),
    )


def build_stock_screen_request_id(keyword: str, market: str = "") -> str:
    now = datetime.now()
    digest = hashlib.sha1(f"{market}|{keyword}|{now.isoformat()}".encode("utf-8")).hexdigest()[:10]
    return f"stock-screen-{now.strftime('%Y%m%d-%H%M%S')}-{digest}"


def run_stock_screen_query(
    *,
    keyword: str,
    settings: StockScreenSettings,
    market: str = "",
    page_no: int = 1,
    page_size: int = 0,
    fetch_all: bool | None = None,
    request_id: str = "",
    export_dir: str | Path | None = None,
    request_page: PageRequestFn | None = None,
) -> dict[str, Any]:
    requested_keyword = str(keyword or "").strip()
    if not requested_keyword:
        raise StockScreenError("keyword is required", status_code=400)

    normalized_market = str(market or "").strip()
    if normalized_market and normalized_market not in SUPPORTED_MARKETS:
        supported = ", ".join(sorted(SUPPORTED_MARKETS))
        raise StockScreenError(f"unsupported market: {normalized_market}; supported: {supported}", status_code=400)

    api_key = os.getenv(settings.api_key_env, "").strip()
    if not api_key:
        raise StockScreenError(f"missing env {settings.api_key_env}", status_code=500)

    effective_page_size = max(page_size or settings.default_page_size, 1)
    fetch_all_pages = settings.fetch_all_pages if fetch_all is None else to_bool(fetch_all, settings.fetch_all_pages)
    effective_keyword = _build_effective_keyword(requested_keyword, normalized_market)
    effective_request_id = request_id or build_stock_screen_request_id(requested_keyword, normalized_market)
    _validate_request_id(effective_request_id)
    page_request_fn = request_page or _request_stock_screen_page

    first_page_no = 1 if fetch_all_pages else max(page_no, 1)
    first_page_payload = page_request_fn(
        {
            "keyword": effective_keyword,
            "pageNo": first_page_no,
            "pageSize": effective_page_size,
        },
        settings,
        api_key,
    )
    parsed_first_page = _parse_stock_screen_payload(first_page_payload)
    raw_pages = [first_page_payload]
    raw_rows = list(parsed_first_page["rows"])
    total_records = max(parsed_first_page["total"], len(raw_rows))
    total_pages = max(math.ceil(total_records / effective_page_size), 1) if total_records else 1

    if fetch_all_pages and total_pages > settings.max_pages:
        raise StockScreenError(
            f"result requires {total_pages} pages, which exceeds max_pages={settings.max_pages}",
            status_code=400,
        )

    if fetch_all_pages:
        for current_page in range(2, total_pages + 1):
            page_payload = page_request_fn(
                {
                    "keyword": effective_keyword,
                    "pageNo": current_page,
                    "pageSize": effective_page_size,
                },
                settings,
                api_key,
            )
            raw_pages.append(page_payload)
            parsed_page = _parse_stock_screen_payload(page_payload)
            raw_rows.extend(parsed_page["rows"])

    localized_columns = _build_localized_columns(parsed_first_page["columns"], raw_rows)
    localized_rows = _localize_rows(raw_rows, localized_columns)
    unique_total = total_records or len(localized_rows)

    artifacts: dict[str, str] = {}
    if export_dir is not None:
        artifacts = _export_stock_screen_artifacts(
            export_dir=Path(export_dir),
            request_id=effective_request_id,
            requested_keyword=requested_keyword,
            effective_keyword=effective_keyword,
            market=normalized_market,
            page_size=effective_page_size,
            pages_fetched=len(raw_pages),
            raw_pages=raw_pages,
            parsed_first_page=parsed_first_page,
            localized_columns=localized_columns,
            localized_rows=localized_rows,
            total_records=unique_total,
        )

    return {
        "request_id": effective_request_id,
        "keyword": requested_keyword,
        "effective_keyword": effective_keyword,
        "market": normalized_market,
        "status": parsed_first_page["status"],
        "message": parsed_first_page["message"],
        "business_code": parsed_first_page["business_code"],
        "business_msg": parsed_first_page["business_msg"],
        "result_type": parsed_first_page["result_type"],
        "total": unique_total,
        "row_count": len(localized_rows),
        "page_size": effective_page_size,
        "pages_fetched": len(raw_pages),
        "fetch_all": fetch_all_pages,
        "parser_text": parsed_first_page["parser_text"],
        "response_conditions": parsed_first_page["response_conditions"],
        "total_condition": parsed_first_page["total_condition"],
        "columns": localized_columns,
        "rows": localized_rows,
        "artifacts": artifacts,
    }


def _build_effective_keyword(keyword: str, market: str) -> str:
    if not market:
        return keyword
    if any(token in keyword for token in SUPPORTED_MARKETS):
        return keyword
    return f"{market}{keyword}"


def _request_stock_screen_page(
    payload: dict[str, Any],
    settings: StockScreenSettings,
    api_key: str,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        settings.endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "apikey": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        snippet = body.strip().replace("\n", " ")[:240]
        raise StockScreenError(f"stock_screen_http_error:{exc.code}:{snippet}", status_code=502) from exc
    except URLError as exc:
        raise StockScreenError(f"stock_screen_network_error:{exc.reason}", status_code=502) from exc
    except TimeoutError as exc:
        raise StockScreenError("stock_screen_timeout", status_code=504) from exc

    try:
        loaded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise StockScreenError(f"stock_screen_invalid_json:{exc}", status_code=502) from exc

    if not isinstance(loaded, dict):
        raise StockScreenError("stock_screen_invalid_payload", status_code=502)
    return loaded


def _validate_request_id(value: str) -> None:
    if not value:
        raise StockScreenError("request_id is required", status_code=400)
    if any(char not in REQUEST_ID_ALLOWED_CHARS for char in value):
        raise StockScreenError("request_id contains unsupported characters", status_code=400)


def _parse_stock_screen_payload(payload: dict[str, Any]) -> dict[str, Any]:
    status = to_int(payload.get("status"), -1)
    message = str(payload.get("message") or "")
    if status != 0:
        raise StockScreenError(message or "stock_screen_upstream_failed", status_code=502)

    business = payload.get("data") or {}
    if not isinstance(business, dict):
        raise StockScreenError("stock_screen_business_payload_invalid", status_code=502)

    business_code = str(business.get("code") or "")
    business_msg = str(business.get("msg") or "")
    if business_code and business_code != "100":
        raise StockScreenError(business_msg or f"stock_screen_business_failed:{business_code}", status_code=400)

    inner = business.get("data") or {}
    if not isinstance(inner, dict):
        raise StockScreenError("stock_screen_data_payload_invalid", status_code=502)

    result = inner.get("result") or {}
    if not isinstance(result, dict) or not result:
        all_results = inner.get("allResults") or {}
        if isinstance(all_results, dict):
            result = all_results.get("result") or result
    if not isinstance(result, dict):
        raise StockScreenError("stock_screen_result_payload_invalid", status_code=502)

    columns = result.get("columns") or []
    rows = result.get("dataList") or []
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise StockScreenError("stock_screen_rows_payload_invalid", status_code=502)

    total = max(
        to_int(result.get("total"), len(rows)),
        to_int(result.get("totalRecordCount"), len(rows)),
        len(rows),
    )

    response_conditions = inner.get("responseConditionList") or []
    if not isinstance(response_conditions, list):
        response_conditions = []

    total_condition = inner.get("totalCondition") or {}
    if not isinstance(total_condition, dict):
        total_condition = {}

    return {
        "status": status,
        "message": message,
        "business_code": business_code,
        "business_msg": business_msg,
        "result_type": to_int(inner.get("resultType"), 0),
        "columns": [item for item in columns if isinstance(item, dict)],
        "rows": [item for item in rows if isinstance(item, dict)],
        "total": total,
        "parser_text": str(inner.get("parserText") or ""),
        "response_conditions": response_conditions,
        "total_condition": total_condition,
    }


def _build_localized_columns(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    for column in columns:
        key = str(column.get("key") or "").strip()
        if not key:
            continue
        by_key[key] = column
        ordered_keys.append(key)

    for row in rows:
        for key in row.keys():
            normalized_key = str(key).strip()
            if not normalized_key or normalized_key in by_key:
                continue
            by_key[normalized_key] = {"key": normalized_key, "title": normalized_key}
            ordered_keys.append(normalized_key)

    seen_headers: dict[str, int] = {}
    localized_columns: list[dict[str, Any]] = []
    for index, key in enumerate(ordered_keys, start=1):
        column = by_key.get(key, {})
        title = str(column.get("title") or key).strip() or key
        csv_header = title
        duplicate_count = seen_headers.get(csv_header, 0)
        if duplicate_count > 0:
            csv_header = f"{title}[{key}]"
        seen_headers[title] = duplicate_count + 1
        localized_columns.append(
            {
                "index": index,
                "key": key,
                "csv_header": csv_header,
                "title": title,
                "unit": str(column.get("unit") or ""),
                "date_msg": str(column.get("dateMsg") or ""),
                "data_type": str(column.get("dataType") or ""),
                "sortable": bool(column.get("sortable", False)),
                "sort_way": str(column.get("sortWay") or ""),
                "red_green_able": bool(column.get("redGreenAble", False)),
            }
        )
    return localized_columns


def _localize_rows(rows: list[dict[str, Any]], localized_columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    localized_rows: list[dict[str, Any]] = []
    ordered_pairs = [(str(column["key"]), str(column["csv_header"])) for column in localized_columns]
    for row in rows:
        localized_rows.append({header: row.get(key) for key, header in ordered_pairs})
    return localized_rows


def _export_stock_screen_artifacts(
    *,
    export_dir: Path,
    request_id: str,
    requested_keyword: str,
    effective_keyword: str,
    market: str,
    page_size: int,
    pages_fetched: int,
    raw_pages: list[dict[str, Any]],
    parsed_first_page: dict[str, Any],
    localized_columns: list[dict[str, Any]],
    localized_rows: list[dict[str, Any]],
    total_records: int,
) -> dict[str, str]:
    export_dir.mkdir(parents=True, exist_ok=True)

    csv_path = export_dir / "stock_screen_result.csv"
    description_path = export_dir / "stock_screen_description.json"
    raw_result_path = export_dir / "stock_screen_raw.json"

    fieldnames = [str(column["csv_header"]) for column in localized_columns]
    write_csv(csv_path, localized_rows, fieldnames)
    write_json(
        description_path,
        {
            "request_id": request_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "keyword": requested_keyword,
            "effective_keyword": effective_keyword,
            "market": market,
            "page_size": page_size,
            "pages_fetched": pages_fetched,
            "total": total_records,
            "row_count": len(localized_rows),
            "status": parsed_first_page["status"],
            "message": parsed_first_page["message"],
            "business_code": parsed_first_page["business_code"],
            "business_msg": parsed_first_page["business_msg"],
            "result_type": parsed_first_page["result_type"],
            "parser_text": parsed_first_page["parser_text"],
            "response_conditions": parsed_first_page["response_conditions"],
            "total_condition": parsed_first_page["total_condition"],
            "columns": localized_columns,
        },
    )
    write_json(
        raw_result_path,
        {
            "request_id": request_id,
            "pages_fetched": pages_fetched,
            "pages": raw_pages,
        },
    )

    return {
        "directory": str(export_dir),
        "csv": str(csv_path),
        "description_json": str(description_path),
        "raw_json": str(raw_result_path),
    }


__all__ = [
    "DEFAULT_STOCK_SCREEN_ENDPOINT",
    "StockScreenError",
    "StockScreenSettings",
    "build_stock_screen_request_id",
    "load_stock_screen_settings",
    "run_stock_screen_query",
]
