from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from typing import Any, get_type_hints


class RowModel:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def field_names(cls) -> list[str]:
        return list(_row_field_names(cls))

    @classmethod
    def field_types(cls) -> dict[str, Any]:
        return dict(_row_field_types(cls))


class StageOutputModel:
    def to_updates(self) -> dict[str, Any]:
        raise NotImplementedError


@lru_cache(maxsize=None)
def _row_field_names(model_type: type[RowModel]) -> tuple[str, ...]:
    return tuple(field.name for field in fields(model_type))


@lru_cache(maxsize=None)
def _row_field_types(model_type: type[RowModel]) -> tuple[tuple[str, Any], ...]:
    return tuple(get_type_hints(model_type).items())


def _serialize_row(value: RowModel) -> dict[str, Any]:
    return value.to_dict()


def _serialize_rows(values: list[RowModel]) -> list[dict[str, Any]]:
    return [_serialize_row(value) for value in values]


def _serialize_mapping(value: RowModel) -> dict[str, Any]:
    return _serialize_row(value)


def _serialize_named_mapping(values: dict[str, RowModel]) -> dict[str, dict[str, Any]]:
    return {str(key): _serialize_mapping(value) for key, value in values.items()}


@dataclass(frozen=True)
class TechCandidateRow(RowModel):
    trade_date: str
    symbol: str
    name: str
    sector: str
    board: str
    last_price: float
    prev_close: float
    upper_limit: float
    lower_limit: float
    rule_pass: bool
    tech_score: float
    momentum_score: float
    breakout_score: float
    liquidity_score: float
    turnover_rate: float
    turnover_rate_proxy: float
    relative_volume: float
    relative_amount: float
    amount: float
    daily_pct_change: float
    return_5d: float
    return_20d: float
    ma20: float
    ma60: float
    price_vs_ma20: float
    price_vs_20d_high: float
    volatility_20d: float
    near_upper_limit: bool
    is_st: bool
    suspended: bool
    list_days: int
    market_data_source: str
    technical_flags: str
    technical_summary: str
    trigger_tags: str


@dataclass(frozen=True)
class MetricsSummary(RowModel):
    run_id: str
    trade_date: str
    daily_return: float
    cum_return: float
    max_drawdown: float
    trading_fees: float
    sharpe_ratio: float
    win_rate: float
    risk_intercept_count: int
    filled_order_count: int
    accepted_order_count: int
    limit_no_fill_count: int
    total_buy_orders: int
    total_sell_orders: int
    selector_failed: bool
    risk_mode: str


@dataclass(frozen=True)
class PositionSnapshotRow(RowModel):
    trade_date: str
    symbol: str
    name: str
    sector: str
    board: str
    quantity: float
    available_quantity: float
    avg_cost: float
    prev_close: float
    last_price: float
    upper_limit: float
    lower_limit: float
    market_value: float
    current_weight: float
    unrealized_pnl_pct: float
    is_st: bool
    suspended: bool
    list_days: float
    last_trade_date: str
    t_plus_one_locked: bool
    event_score: float


@dataclass(frozen=True)
class HoldingActionRow(RowModel):
    trade_date: str
    symbol: str
    name: str
    sector: str
    board: str
    quantity: float
    available_quantity: float
    avg_cost: float
    prev_close: float
    last_price: float
    upper_limit: float
    lower_limit: float
    current_weight: float
    action_today: str
    target_weight: float
    stop_loss: float
    take_profit: float
    risk_level: str
    is_st: bool
    suspended: bool
    list_days: float
    reason: str
    last_trade_date: str
    t_plus_one_locked: bool


@dataclass(frozen=True)
class NewsSearchItemRow(RowModel):
    title: str
    date: str
    information_type: str
    jump_url: str
    excerpt: str


@dataclass(frozen=True)
class NewsSearchView(RowModel):
    source: str
    query: str
    count: int
    news_search_score: float
    summary: str
    items: list[NewsSearchItemRow]


@dataclass(frozen=True)
class AIInsightRow(RowModel):
    trade_date: str
    symbol: str
    name: str
    sector: str
    board: str
    action_hint: str
    confidence: float
    tech_score: float
    market_technical_score: float
    news_event_score: float
    fundamental_score: float
    combined_score: float
    market_data_source: str
    technical_summary: str
    thesis: str
    risk_flags: str


@dataclass(frozen=True)
class OrderCandidateRow(RowModel):
    trade_date: str
    order_id: str
    symbol: str
    name: str
    sector: str
    board: str
    action: str
    w_ai: float
    w_candidate: float
    target_weight: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    reduce_price: float
    exit_price: float
    reason: str
    confidence: float


@dataclass(frozen=True)
class TradePlanRow(RowModel):
    trade_date: str
    order_id: str
    symbol: str
    name: str
    sector: str
    board: str
    action: str
    w_ai: float
    w_candidate: float
    target_weight: float
    w_final: float
    status: str
    cap_hit_reason: str
    risk_mode: str
    entry_price_final: float
    stop_loss_price_final: float
    take_profit_price_final: float
    reduce_price_final: float
    exit_price_final: float
    reason: str


@dataclass(frozen=True)
class RiskEventRow(RowModel):
    order_id: str
    symbol: str
    action: str
    status: str
    reason: str


@dataclass(frozen=True)
class SimFillRow(RowModel):
    trade_date: str
    order_id: str
    symbol: str
    name: str
    board: str
    action: str
    planned_price: float
    fill_price: float
    price_deviation_bps: float
    quantity: float
    filled_amount: float
    commission: float
    stamp_duty: float
    transfer_fee: float
    total_fee: float
    status: str
    note: str


@dataclass(frozen=True)
class PositionRow(RowModel):
    trade_date: str
    symbol: str
    name: str
    sector: str
    board: str
    quantity: float
    available_quantity: float
    avg_cost: float
    prev_close: float
    last_price: float
    upper_limit: float
    lower_limit: float
    market_value: float
    weight: float
    unrealized_pnl_pct: float
    is_st: bool
    suspended: bool
    last_trade_date: str


@dataclass(frozen=True)
class NavRow(RowModel):
    trade_date: str
    cash: float
    market_value: float
    total_equity: float
    trading_fees: float
    daily_return: float
    cum_return: float
    max_drawdown: float
    filled_order_count: int


@dataclass(frozen=True)
class HoldingReviewStageOutput(StageOutputModel):
    account: dict[str, Any]
    risk_mode: str
    positions_prev: list[PositionSnapshotRow]
    positions: list[PositionSnapshotRow]
    holding_actions: list[HoldingActionRow]

    def to_updates(self) -> dict[str, Any]:
        return {
            "account": dict(self.account),
            "risk_mode": self.risk_mode,
            "positions_prev": _serialize_rows(self.positions_prev),
            "positions": _serialize_rows(self.positions),
            "holding_actions": _serialize_rows(self.holding_actions),
        }


@dataclass(frozen=True)
class SelectorStageOutput(StageOutputModel):
    tech_candidates: list[TechCandidateRow]
    selector_watchlist: list[dict[str, Any]]
    selector_source: str
    stock_screen_result: dict[str, Any]
    selector_failed: bool = False

    def to_updates(self) -> dict[str, Any]:
        return {
            "tech_candidates": _serialize_rows(self.tech_candidates),
            "selector_watchlist": list(self.selector_watchlist),
            "selector_source": self.selector_source,
            "stock_screen_result": dict(self.stock_screen_result),
            "selector_failed": self.selector_failed,
        }


@dataclass(frozen=True)
class ReporterStageOutput(StageOutputModel):
    metrics: MetricsSummary
    risk_report_markdown: str

    def to_updates(self) -> dict[str, Any]:
        return {
            "metrics": _serialize_mapping(self.metrics),
            "risk_report_markdown": self.risk_report_markdown,
        }


@dataclass(frozen=True)
class AnalystStageOutput(StageOutputModel):
    ai_insights: list[AIInsightRow]
    analyst_news_search: dict[str, NewsSearchView]

    def to_updates(self) -> dict[str, Any]:
        return {
            "ai_insights": _serialize_rows(self.ai_insights),
            "analyst_news_search": _serialize_named_mapping(self.analyst_news_search),
        }


@dataclass(frozen=True)
class DeciderStageOutput(StageOutputModel):
    orders_candidate: list[OrderCandidateRow]

    def to_updates(self) -> dict[str, Any]:
        return {
            "orders_candidate": _serialize_rows(self.orders_candidate),
        }


@dataclass(frozen=True)
class RiskGuardStageOutput(StageOutputModel):
    trade_plan: list[TradePlanRow]
    risk_events: list[RiskEventRow]
    risk_guard_failed: bool

    def to_updates(self) -> dict[str, Any]:
        return {
            "trade_plan": _serialize_rows(self.trade_plan),
            "risk_events": _serialize_rows(self.risk_events),
            "risk_guard_failed": self.risk_guard_failed,
        }


@dataclass(frozen=True)
class ExecutorStageOutput(StageOutputModel):
    sim_fill: list[SimFillRow]
    positions: list[PositionRow]
    nav: list[NavRow]
    executor_failed: bool

    def to_updates(self) -> dict[str, Any]:
        return {
            "sim_fill": _serialize_rows(self.sim_fill),
            "positions": _serialize_rows(self.positions),
            "nav": _serialize_rows(self.nav),
            "executor_failed": self.executor_failed,
        }
