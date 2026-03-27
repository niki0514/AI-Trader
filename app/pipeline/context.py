from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunContext:
    run_id: str
    trade_date: str
    config: dict[str, Any]
    input_path: Path
    output_root: Path
    output_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)

    def ensure_output_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "stages").mkdir(parents=True, exist_ok=True)

    def stage_output_path(self, stage_index: int, stage_name: str) -> Path:
        return self.output_dir / "stages" / f"{stage_index:02d}_{stage_name}.json"

    def artifact_path(self, filename: str) -> Path:
        return self.output_dir / filename
