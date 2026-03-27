from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception as exc:
    yaml = None
    YAML_IMPORT_ERROR: Exception | None = exc
else:
    YAML_IMPORT_ERROR = None


def load_pipeline_config(path: str | Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load pipeline config files. "
            "Install backend dependencies with `python3 -m pip install -r requirements.txt`."
        ) from YAML_IMPORT_ERROR
    return _load_config_mapping(Path(path).resolve(), stack=())


def _load_config_mapping(config_path: Path, *, stack: tuple[Path, ...]) -> dict[str, Any]:
    if config_path in stack:
        chain = " -> ".join(str(path) for path in (*stack, config_path))
        raise ValueError(f"Config extends cycle detected: {chain}")

    text = config_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Config at {config_path} is not a mapping.")

    extends_value = loaded.pop("extends", None)
    base_config: dict[str, Any] = {}
    for base_path in _resolve_extends_paths(config_path=config_path, value=extends_value):
        base_config = _deep_merge(base_config, _load_config_mapping(base_path, stack=(*stack, config_path)))
    return _deep_merge(base_config, loaded)


def _resolve_extends_paths(*, config_path: Path, value: Any) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise ValueError(f"Config at {config_path} has invalid extends declaration")
    return [(config_path.parent / candidate).resolve() for candidate in candidates]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(base_value, value)
        else:
            merged[key] = value
    return merged
