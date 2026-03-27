from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters import write_json, write_text
from app.utils import to_bool, to_int


DEFAULT_NEWS_SEARCH_ENDPOINT = "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search"
DEFAULT_NEWS_SEARCH_SIZE = 12
DEFAULT_TIMEOUT_SECONDS = 20
REQUEST_ID_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
HTML_TAG_RE = re.compile(r"<[^>]+>")


class NewsSearchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class NewsSearchSettings:
    endpoint: str
    api_key_env: str
    timeout_seconds: int
    default_size: int


def load_news_search_settings(config: dict[str, Any]) -> NewsSearchSettings:
    news_search_config = config.get("news_search", {})
    return NewsSearchSettings(
        endpoint=str(news_search_config.get("endpoint") or DEFAULT_NEWS_SEARCH_ENDPOINT),
        api_key_env=str(news_search_config.get("api_key_env") or "MX_APIKEY"),
        timeout_seconds=max(to_int(news_search_config.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS), 1),
        default_size=max(to_int(news_search_config.get("default_size"), DEFAULT_NEWS_SEARCH_SIZE), 1),
    )


def build_news_search_request_id(query: str) -> str:
    now = datetime.now()
    digest = hashlib.sha1(f"{query}|{now.isoformat()}".encode("utf-8")).hexdigest()[:10]
    return f"news-search-{now.strftime('%Y%m%d-%H%M%S')}-{digest}"


def run_news_search_query(
    *,
    query: str,
    settings: NewsSearchSettings,
    size: int = 0,
    start_date: str = "",
    end_date: str = "",
    child_search_type: str = "",
    request_id: str = "",
    export_dir: str | Path | None = None,
    request_search: Any | None = None,
) -> dict[str, Any]:
    requested_query = str(query or "").strip()
    if not requested_query:
        raise NewsSearchError("query is required", status_code=400)

    api_key = os.getenv(settings.api_key_env, "").strip()
    if not api_key:
        raise NewsSearchError(f"missing env {settings.api_key_env}", status_code=500)

    effective_size = max(size or settings.default_size, 1)
    effective_request_id = request_id or build_news_search_request_id(requested_query)
    _validate_request_id(effective_request_id)
    request_fn = request_search or _request_news_search

    request_payload: dict[str, Any] = {
        "query": requested_query,
        "size": effective_size,
    }
    if start_date:
        request_payload["inputStartDate"] = str(start_date)
    if end_date:
        request_payload["inputEndDate"] = str(end_date)
    if child_search_type:
        request_payload["childSearchType"] = str(child_search_type)

    raw_payload = request_fn(request_payload, settings, api_key)
    parsed = _parse_news_search_payload(raw_payload)
    normalized_items = _normalize_news_items(parsed["items"])

    artifacts: dict[str, str] = {}
    if export_dir is not None:
        artifacts = _export_news_search_artifacts(
            export_dir=Path(export_dir),
            request_id=effective_request_id,
            query=requested_query,
            parsed=parsed,
            normalized_items=normalized_items,
            raw_payload=raw_payload,
        )

    return {
        "request_id": effective_request_id,
        "query": requested_query,
        "status": parsed["status"],
        "message": parsed["message"],
        "business_status": parsed["business_status"],
        "business_code": parsed["business_code"],
        "business_message": parsed["business_message"],
        "search_status": parsed["search_status"],
        "search_code": parsed["search_code"],
        "search_message": parsed["search_message"],
        "protocol_type": parsed["protocol_type"],
        "trace_id": parsed["trace_id"],
        "search_id": parsed["search_id"],
        "count": len(normalized_items),
        "request": parsed["request"],
        "extra_infos": parsed["extra_infos"],
        "items": normalized_items,
        "artifacts": artifacts,
    }


def _request_news_search(
    payload: dict[str, Any],
    settings: NewsSearchSettings,
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
        raise NewsSearchError(f"news_search_http_error:{exc.code}:{snippet}", status_code=502) from exc
    except URLError as exc:
        raise NewsSearchError(f"news_search_network_error:{exc.reason}", status_code=502) from exc
    except TimeoutError as exc:
        raise NewsSearchError("news_search_timeout", status_code=504) from exc

    try:
        loaded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise NewsSearchError(f"news_search_invalid_json:{exc}", status_code=502) from exc

    if not isinstance(loaded, dict):
        raise NewsSearchError("news_search_invalid_payload", status_code=502)
    return loaded


def _validate_request_id(value: str) -> None:
    if not value:
        raise NewsSearchError("request_id is required", status_code=400)
    if any(char not in REQUEST_ID_ALLOWED_CHARS for char in value):
        raise NewsSearchError("request_id contains unsupported characters", status_code=400)


def _parse_news_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    status = to_int(payload.get("status"), -1)
    message = str(payload.get("message") or "")
    if status != 0:
        raise NewsSearchError(message or "news_search_upstream_failed", status_code=502)

    business = payload.get("data") or {}
    if not isinstance(business, dict):
        raise NewsSearchError("news_search_business_payload_invalid", status_code=502)

    business_status = to_int(business.get("status"), -1)
    business_code = to_int(business.get("code"), -1)
    business_message = str(business.get("message") or "")
    if business_status != 0 or business_code != 0:
        raise NewsSearchError(
            business_message or f"news_search_business_failed:{business_status}:{business_code}",
            status_code=502,
        )

    inner = business.get("data") or {}
    if not isinstance(inner, dict):
        raise NewsSearchError("news_search_data_payload_invalid", status_code=502)

    response = inner.get("llmSearchResponse") or {}
    if not isinstance(response, dict):
        raise NewsSearchError("news_search_response_payload_invalid", status_code=502)

    search_status = to_int(response.get("status"), -1)
    search_code = to_int(response.get("code"), -1)
    search_message = str(response.get("message") or "")
    if search_status != 0 or search_code != 0:
        raise NewsSearchError(
            search_message or f"news_search_failed:{search_status}:{search_code}",
            status_code=502,
        )

    items = response.get("data") or []
    if not isinstance(items, list):
        raise NewsSearchError("news_search_items_payload_invalid", status_code=502)

    request_payload = inner.get("llmSearchRequest") or {}
    if not isinstance(request_payload, dict):
        request_payload = {}

    extra_infos = response.get("extraInfos") or {}
    if not isinstance(extra_infos, dict):
        extra_infos = {}

    return {
        "status": status,
        "message": message,
        "business_status": business_status,
        "business_code": business_code,
        "business_message": business_message,
        "search_status": search_status,
        "search_code": search_code,
        "search_message": search_message,
        "protocol_type": str(inner.get("protocolType") or ""),
        "trace_id": str(response.get("traceId") or request_payload.get("traceId") or ""),
        "search_id": str(inner.get("id") or ""),
        "request": request_payload,
        "extra_infos": extra_infos,
        "items": [item for item in items if isinstance(item, dict)],
    }


def _normalize_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        secu_list = item.get("secuList") or []
        if not isinstance(secu_list, list):
            secu_list = []

        trunk = _resolve_trunk(item)
        normalized.append(
            {
                "index": index,
                "code": str(item.get("code") or ""),
                "title": str(item.get("title") or ""),
                "date": str(item.get("date") or ""),
                "information_type": str(item.get("informationType") or ""),
                "attach_type": str(item.get("attachType") or ""),
                "jump_url": str(item.get("jumpUrl") or ""),
                "rank_score": item.get("rankScore"),
                "index_attention": to_bool(item.get("indexAttention"), False),
                "recall_index": str(item.get("recallIndex") or ""),
                "secu_list": secu_list,
                "trunk": trunk,
                "trunk_excerpt": _truncate(trunk, 240),
                "show_text": str(item.get("showText") or ""),
            }
        )
    return normalized


def _resolve_trunk(item: dict[str, Any]) -> str:
    content = str(item.get("content") or "").strip()
    if content:
        return content
    show_text = str(item.get("showText") or "").strip()
    if show_text:
        return _html_to_text(show_text)
    return ""


def _html_to_text(value: str) -> str:
    text = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</div>", "\n").replace("</tr>", "\n")
    text = text.replace("</td>", " ")
    text = HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _export_news_search_artifacts(
    *,
    export_dir: Path,
    request_id: str,
    query: str,
    parsed: dict[str, Any],
    normalized_items: list[dict[str, Any]],
    raw_payload: dict[str, Any],
) -> dict[str, str]:
    export_dir.mkdir(parents=True, exist_ok=True)

    summary_path = export_dir / "news_search_result.json"
    markdown_path = export_dir / "news_search_result.md"
    raw_path = export_dir / "news_search_raw.json"

    write_json(
        summary_path,
        {
            "request_id": request_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "query": query,
            "protocol_type": parsed["protocol_type"],
            "trace_id": parsed["trace_id"],
            "search_id": parsed["search_id"],
            "count": len(normalized_items),
            "request": parsed["request"],
            "extra_infos": parsed["extra_infos"],
            "items": normalized_items,
        },
    )
    write_text(markdown_path, _build_markdown_report(query=query, parsed=parsed, items=normalized_items))
    write_json(raw_path, raw_payload)

    return {
        "directory": str(export_dir),
        "result_json": str(summary_path),
        "result_markdown": str(markdown_path),
        "raw_json": str(raw_path),
    }


def _build_markdown_report(*, query: str, parsed: dict[str, Any], items: list[dict[str, Any]]) -> str:
    lines = [
        "# 东方财富资讯搜索结果",
        "",
        f"- 查询：{query}",
        f"- 结果数：{len(items)}",
        f"- 协议类型：{parsed['protocol_type'] or '--'}",
        f"- 搜索ID：{parsed['search_id'] or '--'}",
        f"- Trace ID：{parsed['trace_id'] or '--'}",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    if not items:
        lines.extend(["暂无结果。", ""])
        return "\n".join(lines)

    for item in items:
        lines.extend(
            [
                f"## {item['index']}. {item['title'] or '--'}",
                "",
                f"- 时间：{item['date'] or '--'}",
                f"- 类型：{item['information_type'] or '--'}",
                f"- 附件类型：{item['attach_type'] or '--'}",
                f"- 跳转链接：{item['jump_url'] or '--'}",
            ]
        )
        secu_list = item.get("secu_list") or []
        if secu_list:
            secu_text = ", ".join(
                f"{str(secu.get('secuName') or '')}({str(secu.get('secuCode') or '')})"
                for secu in secu_list
                if isinstance(secu, dict)
            )
            lines.append(f"- 关联证券：{secu_text or '--'}")
        lines.extend(
            [
                "",
                item["trunk"] or "暂无正文。",
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


__all__ = [
    "DEFAULT_NEWS_SEARCH_ENDPOINT",
    "NewsSearchError",
    "NewsSearchSettings",
    "build_news_search_request_id",
    "load_news_search_settings",
    "run_news_search_query",
]
