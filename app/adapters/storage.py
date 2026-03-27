from __future__ import annotations

import csv
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from app.pipeline.context import RunContext


def read_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected object from {file_path}, got {type(loaded).__name__}.")
    return loaded


def write_json(path: str | Path, payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(as_jsonable(payload), file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_text(path: str | Path, text: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _as_csv_cell(row.get(name)) for name in fieldnames})


def read_csv(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def dump_stage_output(ctx: RunContext, stage_name: str, stage_index: int, payload: dict[str, Any]) -> None:
    write_json(ctx.stage_output_path(stage_index=stage_index, stage_name=stage_name), payload)


def as_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return as_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [as_jsonable(item) for item in value]
    return value


def _as_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(as_jsonable(value), ensure_ascii=False, sort_keys=True)
    return value
