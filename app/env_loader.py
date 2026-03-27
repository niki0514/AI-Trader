from __future__ import annotations

import os
from pathlib import Path


_ENV_LOADED = False


def load_local_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    for env_path in _candidate_env_files():
        if not env_path.exists() or not env_path.is_file():
            continue
        _load_env_file(env_path)
        break

    _ENV_LOADED = True


def _candidate_env_files() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    return [
        project_root / ".env",
        project_root / "backend" / ".env",
    ]


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or env_key in os.environ:
            continue
        os.environ[env_key] = _normalize_value(value.strip())


def _normalize_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
