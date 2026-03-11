from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


class AnalystLLMError(RuntimeError):
    pass


def request_analyst_text(config: dict[str, Any], prompt: str) -> str:
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
    }
    req = request.Request(endpoint, data=payload, headers=headers, method="POST")

    timeout_seconds = float(llm_config.get("timeout_seconds", 20))
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
    except error.URLError as exc:
        raise AnalystLLMError(str(exc)) from exc

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AnalystLLMError("llm response is not valid json") from exc

    extracted = _extract_text(decoded)
    if not extracted:
        raise AnalystLLMError("llm response missing text")
    return extracted


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("output_text", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                extracted = _extract_text(item)
                if extracted:
                    return extracted
        for value in payload.values():
            extracted = _extract_text(value)
            if extracted:
                return extracted
    if isinstance(payload, list):
        for item in payload:
            extracted = _extract_text(item)
            if extracted:
                return extracted
    return ""
