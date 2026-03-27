from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.outputs import StageOutputModel


@dataclass(frozen=True)
class StageResult:
    updates: dict[str, Any] | StageOutputModel = field(default_factory=dict)
    stage_note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "updates", _coerce_updates(self.updates))


def _coerce_updates(value: dict[str, Any] | StageOutputModel) -> dict[str, Any]:
    if isinstance(value, StageOutputModel):
        return value.to_updates()
    return dict(value)
