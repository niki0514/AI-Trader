from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import error, request


class AnalystLLMError(RuntimeError):
    pass


def require_live_llm(config: dict[str, Any], stage_name: str) -> None:
    if not bool(config.get("llm", {}).get("enable_live", False)):
        raise AnalystLLMError(f"{stage_name} requires llm.enable_live=true")


def request_agent_text(config: dict[str, Any], prompt: str) -> str:
    decoded = _request_response_payload(config, prompt)
    extracted = _extract_text(decoded)
    if not extracted:
        raise AnalystLLMError("llm response missing text")
    return extracted


def request_agent_json(config: dict[str, Any], prompt: str) -> dict[str, Any] | list[Any]:
    text = request_agent_text(config, prompt)
    parsed = _parse_json_text(text)
    if not isinstance(parsed, (dict, list)):
        raise AnalystLLMError("llm json response must be object or array")
    return parsed


def _request_response_payload(config: dict[str, Any], prompt: str) -> dict[str, Any]:
    llm_config = config.get("llm", {})
    provider = str(llm_config.get("provider", "mock")).lower()
    if provider == "mock":
        raise AnalystLLMError("mock provider enabled")

    endpoint = str(llm_config.get("endpoint", "")).strip()
    if not endpoint:
        raise AnalystLLMError("missing llm endpoint")

    api_key_env = str(llm_config.get("api_key_env", "GMN_API_KEY"))
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise AnalystLLMError(f"missing env {api_key_env}")

    body = {
        "model": llm_config.get("model", ""),
        "input": prompt,
        "temperature": float(llm_config.get("temperature", 0.2)),
        "max_output_tokens": int(llm_config.get("max_output_tokens", 512)),
    }
    payload = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": str(llm_config.get("user_agent", "codex-rs/1.0.7")),
    }
    req = request.Request(endpoint, data=payload, headers=headers, method="POST")

    timeout_seconds = float(llm_config.get("timeout_seconds", 20))
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        details = error_body[:500] if error_body else exc.reason
        raise AnalystLLMError(f"HTTP Error {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise AnalystLLMError(str(exc)) from exc
    except TimeoutError as exc:
        raise AnalystLLMError("llm request timed out") from exc
    except OSError as exc:
        raise AnalystLLMError(str(exc)) from exc

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AnalystLLMError("llm response is not valid json") from exc
    if not isinstance(decoded, dict):
        raise AnalystLLMError("llm response root must be an object")
    return decoded


def _extract_text(payload: Any) -> str:
    if isinstance(payload, dict):
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = payload.get("output")
        if isinstance(output, list):
            texts = _collect_output_text(output)
            if texts:
                return "\n".join(texts).strip()

        content = payload.get("content")
        if isinstance(content, list):
            texts = _collect_output_text(content)
            if texts:
                return "\n".join(texts).strip()

        if payload.get("type") == "output_text":
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    if isinstance(payload, list):
        texts = _collect_output_text(payload)
        if texts:
            return "\n".join(texts).strip()
    if isinstance(payload, str):
        return payload.strip()
    return ""


def _collect_output_text(payload: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(payload, dict):
        if payload.get("type") == "output_text":
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        content = payload.get("content")
        if isinstance(content, list):
            for item in content:
                texts.extend(_collect_output_text(item))
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                texts.extend(_collect_output_text(item))
    elif isinstance(payload, list):
        for item in payload:
            texts.extend(_collect_output_text(item))
    return texts


def _parse_json_text(text: str) -> Any:
    cleaned = text.strip()
    candidates: list[str] = []
    if cleaned:
        candidates.append(cleaned)

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidates.append(cleaned[start : end + 1].strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise AnalystLLMError("llm response is not valid json text")
