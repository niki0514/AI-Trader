from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _coerce_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


@dataclass(frozen=True)
class SnapshotBundle:
    trade_date: str
    snapshot: dict[str, Any]
    snapshot_market: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SnapshotBundle:
        trade_date = str(payload.get("trade_date") or "")
        return cls(
            trade_date=trade_date,
            snapshot=_coerce_mapping(payload.get("snapshot")),
            snapshot_market=_coerce_mapping(payload.get("snapshot_market")),
        )

    @property
    def effective_snapshot(self) -> dict[str, Any]:
        return self.snapshot_market or self.snapshot

    @property
    def watchlist(self) -> list[dict[str, Any]]:
        return _coerce_rows(self.effective_snapshot.get("watchlist"))

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        return _coerce_rows(self.snapshot.get("recent_events"))

    @property
    def fundamentals(self) -> list[dict[str, Any]]:
        return _coerce_rows(self.snapshot.get("fundamentals"))

    @property
    def selector_query(self) -> dict[str, Any]:
        return _coerce_mapping(self.snapshot.get("selector_query"))


@dataclass(frozen=True)
class PortfolioState:
    account: dict[str, Any]
    positions_prev: list[dict[str, Any]]
    risk_mode: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PortfolioState:
        return cls(
            account=_coerce_mapping(payload.get("account")),
            positions_prev=_coerce_rows(payload.get("positions_prev")),
            risk_mode=str(payload.get("risk_mode") or "NEUTRAL"),
        )


@dataclass(frozen=True)
class SelectorStageInput:
    snapshots: SnapshotBundle

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SelectorStageInput:
        return cls(snapshots=SnapshotBundle.from_payload(payload))


@dataclass(frozen=True)
class HoldingReviewStageInput:
    snapshots: SnapshotBundle

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> HoldingReviewStageInput:
        return cls(snapshots=SnapshotBundle.from_payload(payload))


@dataclass(frozen=True)
class AnalystStageInput:
    snapshots: SnapshotBundle
    portfolio: PortfolioState
    tech_candidates: list[dict[str, Any]]
    selector_source: str
    selector_watchlist: list[dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AnalystStageInput:
        return cls(
            snapshots=SnapshotBundle.from_payload(payload),
            portfolio=PortfolioState.from_payload(payload),
            tech_candidates=_coerce_rows(payload.get("tech_candidates")),
            selector_source=str(payload.get("selector_source") or "snapshot"),
            selector_watchlist=_coerce_rows(payload.get("selector_watchlist")),
        )


@dataclass(frozen=True)
class DeciderStageInput:
    snapshots: SnapshotBundle
    portfolio: PortfolioState
    holding_actions: list[dict[str, Any]]
    ai_insights: list[dict[str, Any]]
    selector_watchlist: list[dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DeciderStageInput:
        return cls(
            snapshots=SnapshotBundle.from_payload(payload),
            portfolio=PortfolioState.from_payload(payload),
            holding_actions=_coerce_rows(payload.get("holding_actions")),
            ai_insights=_coerce_rows(payload.get("ai_insights")),
            selector_watchlist=_coerce_rows(payload.get("selector_watchlist")),
        )

    @property
    def candidate_price_rows(self) -> list[dict[str, Any]]:
        return self.selector_watchlist or self.snapshots.watchlist


@dataclass(frozen=True)
class RiskGuardStageInput:
    portfolio: PortfolioState
    orders_candidate: list[dict[str, Any]]
    tech_candidates: list[dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RiskGuardStageInput:
        return cls(
            portfolio=PortfolioState.from_payload(payload),
            orders_candidate=_coerce_rows(payload.get("orders_candidate")),
            tech_candidates=_coerce_rows(payload.get("tech_candidates")),
        )


@dataclass(frozen=True)
class ExecutorStageInput:
    portfolio: PortfolioState
    snapshots: SnapshotBundle
    trade_plan: list[dict[str, Any]]
    selector_watchlist: list[dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ExecutorStageInput:
        return cls(
            portfolio=PortfolioState.from_payload(payload),
            snapshots=SnapshotBundle.from_payload(payload),
            trade_plan=_coerce_rows(payload.get("trade_plan")),
            selector_watchlist=_coerce_rows(payload.get("selector_watchlist")),
        )

    @property
    def execution_watchlist(self) -> list[dict[str, Any]]:
        return self.selector_watchlist or self.snapshots.watchlist


@dataclass(frozen=True)
class ReporterStageInput:
    snapshots: SnapshotBundle
    portfolio: PortfolioState
    run_id: str
    trade_plan: list[dict[str, Any]]
    sim_fill: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    nav: list[dict[str, Any]]
    risk_events: list[dict[str, Any]]
    stage_notes: dict[str, Any]
    selector_failed: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ReporterStageInput:
        return cls(
            snapshots=SnapshotBundle.from_payload(payload),
            portfolio=PortfolioState.from_payload(payload),
            run_id=str(payload.get("run_id") or ""),
            trade_plan=_coerce_rows(payload.get("trade_plan")),
            sim_fill=_coerce_rows(payload.get("sim_fill")),
            positions=_coerce_rows(payload.get("positions")),
            nav=_coerce_rows(payload.get("nav")),
            risk_events=_coerce_rows(payload.get("risk_events")),
            stage_notes=_coerce_mapping(payload.get("stage_notes")),
            selector_failed=bool(payload.get("selector_failed", False)),
        )

    @property
    def nav_row(self) -> dict[str, Any]:
        if not self.nav:
            return {}
        return dict(self.nav[-1])


@dataclass(frozen=True)
class HoldingActionsArtifactView:
    holding_actions: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> HoldingActionsArtifactView:
        return cls(holding_actions=_coerce_rows(stage_outputs.get("holding_actions")))


@dataclass(frozen=True)
class SelectorArtifactView:
    tech_candidates: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> SelectorArtifactView:
        return cls(tech_candidates=_coerce_rows(stage_outputs.get("tech_candidates")))


@dataclass(frozen=True)
class AnalystArtifactView:
    ai_insights: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> AnalystArtifactView:
        return cls(ai_insights=_coerce_rows(stage_outputs.get("ai_insights")))


@dataclass(frozen=True)
class DeciderArtifactView:
    orders_candidate: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> DeciderArtifactView:
        return cls(orders_candidate=_coerce_rows(stage_outputs.get("orders_candidate")))


@dataclass(frozen=True)
class RiskGuardArtifactView:
    trade_plan: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> RiskGuardArtifactView:
        return cls(trade_plan=_coerce_rows(stage_outputs.get("trade_plan")))


@dataclass(frozen=True)
class ExecutorArtifactView:
    sim_fill: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    nav: list[dict[str, Any]]

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> ExecutorArtifactView:
        return cls(
            sim_fill=_coerce_rows(stage_outputs.get("sim_fill")),
            positions=_coerce_rows(stage_outputs.get("positions")),
            nav=_coerce_rows(stage_outputs.get("nav")),
        )


@dataclass(frozen=True)
class ReporterArtifactView:
    metrics: dict[str, Any]
    risk_report_markdown: str

    @classmethod
    def from_stage_outputs(cls, stage_outputs: dict[str, Any]) -> ReporterArtifactView:
        return cls(
            metrics=_coerce_mapping(stage_outputs.get("metrics")),
            risk_report_markdown=str(stage_outputs.get("risk_report_markdown") or ""),
        )
