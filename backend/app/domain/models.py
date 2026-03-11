from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import RiskMode


@dataclass
class AccountSnapshot:
    cash: float
    total_equity: float
    previous_total_equity: float
    initial_total_equity: float
    portfolio_drawdown_pct: float = 0.0
    market_regime: str = RiskMode.NEUTRAL.value
    industry_exposure: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AccountSnapshot":
        total_equity = float(raw.get("total_equity", 0.0))
        previous_total_equity = float(raw.get("previous_total_equity", total_equity))
        initial_total_equity = float(raw.get("initial_total_equity", previous_total_equity or total_equity))
        return cls(
            cash=float(raw.get("cash", 0.0)),
            total_equity=total_equity,
            previous_total_equity=previous_total_equity,
            initial_total_equity=initial_total_equity,
            portfolio_drawdown_pct=float(raw.get("portfolio_drawdown_pct", 0.0)),
            market_regime=normalize_token(raw.get("market_regime"), RiskMode.NEUTRAL.value),
            industry_exposure={
                str(key): float(value)
                for key, value in (raw.get("industry_exposure") or {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": round(self.cash, 2),
            "total_equity": round(self.total_equity, 2),
            "previous_total_equity": round(self.previous_total_equity, 2),
            "initial_total_equity": round(self.initial_total_equity, 2),
            "portfolio_drawdown_pct": round(self.portfolio_drawdown_pct, 4),
            "market_regime": self.market_regime,
            "industry_exposure": {
                key: round(value, 4) for key, value in sorted(self.industry_exposure.items())
            },
        }


@dataclass
class PositionSnapshot:
    symbol: str
    quantity: float
    avg_cost: float
    last_price: float
    name: str = ""
    industry: str = "UNKNOWN"
    liquidity_score: float = 0.6
    available_quantity: float = 0.0
    t1_locked: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PositionSnapshot":
        quantity = float(raw.get("quantity", 0.0))
        return cls(
            symbol=str(raw["symbol"]),
            quantity=quantity,
            avg_cost=float(raw.get("avg_cost", 0.0)),
            last_price=float(raw.get("last_price", 0.0)),
            name=str(raw.get("name", "")),
            industry=str(raw.get("industry", "UNKNOWN")),
            liquidity_score=clamp(float(raw.get("liquidity_score", 0.6))),
            available_quantity=float(raw.get("available_quantity", quantity)),
            t1_locked=bool(raw.get("t1_locked", False)),
        )

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_cost <= 0:
            return 0.0
        return (self.last_price - self.avg_cost) / self.avg_cost

    def current_weight(self, total_equity: float) -> float:
        if total_equity <= 0:
            return 0.0
        return self.market_value / total_equity

    def to_dict(self, total_equity: float | None = None) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "name": self.name,
            "industry": self.industry,
            "quantity": round(self.quantity, 4),
            "avg_cost": round(self.avg_cost, 4),
            "last_price": round(self.last_price, 4),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 4),
            "liquidity_score": round(self.liquidity_score, 4),
            "available_quantity": round(self.available_quantity, 4),
            "t1_locked": self.t1_locked,
        }
        if total_equity is not None:
            payload["current_weight"] = round(self.current_weight(total_equity), 4)
        return payload


@dataclass
class WatchlistCandidate:
    symbol: str
    name: str
    industry: str
    last_price: float
    momentum_score: float
    value_score: float
    news_score: float
    breakout_score: float
    pullback_score: float
    volatility_score: float
    liquidity_score: float
    profitability_score: float
    growth_score: float
    valuation_score: float
    quality_score: float
    event_score: float
    realtime_headline: str
    realtime_summary: str

    @classmethod
    def from_sources(
        cls,
        raw: dict[str, Any],
        fundamentals: dict[str, Any] | None = None,
        realtime_info: dict[str, Any] | None = None,
    ) -> "WatchlistCandidate":
        price_features = raw.get("price_features") or {}
        fundamentals = fundamentals or raw.get("fundamentals") or {}
        realtime_info = realtime_info or raw.get("realtime_info") or {}
        return cls(
            symbol=str(raw["symbol"]),
            name=str(raw.get("name", "")),
            industry=str(raw.get("industry", "UNKNOWN")),
            last_price=float(raw.get("last_price", 0.0)),
            momentum_score=float(raw.get("momentum_score", 0.0)),
            value_score=float(raw.get("value_score", 0.0)),
            news_score=float(raw.get("news_score", 0.0)),
            breakout_score=float(price_features.get("breakout_score", raw.get("breakout_score", raw.get("momentum_score", 0.0)))),
            pullback_score=float(price_features.get("pullback_score", raw.get("pullback_score", raw.get("value_score", 0.0)))),
            volatility_score=clamp(float(price_features.get("volatility_score", raw.get("volatility_score", 0.35)))),
            liquidity_score=clamp(float(raw.get("liquidity_score", price_features.get("liquidity_score", 0.6)))),
            profitability_score=clamp(float(fundamentals.get("profitability_score", raw.get("profitability_score", raw.get("value_score", 0.5))))),
            growth_score=clamp(float(fundamentals.get("growth_score", raw.get("growth_score", raw.get("momentum_score", 0.5))))),
            valuation_score=clamp(float(fundamentals.get("valuation_score", raw.get("valuation_score", raw.get("value_score", 0.5))))),
            quality_score=clamp(float(fundamentals.get("quality_score", raw.get("quality_score", raw.get("value_score", 0.5))))),
            event_score=clamp(float(realtime_info.get("event_score", raw.get("event_score", raw.get("news_score", 0.0))))),
            realtime_headline=str(realtime_info.get("headline", raw.get("headline", ""))),
            realtime_summary=str(realtime_info.get("summary", raw.get("realtime_summary", ""))),
        )

    @property
    def tech_score(self) -> float:
        return clamp(
            (self.momentum_score * 0.40)
            + (self.breakout_score * 0.25)
            + (self.pullback_score * 0.15)
            + ((1.0 - self.volatility_score) * 0.10)
            + (self.news_score * 0.10)
        )

    @property
    def news_event_score(self) -> float:
        return clamp((self.news_score * 0.55) + (self.event_score * 0.45))

    @property
    def fundamental_score(self) -> float:
        return clamp(
            (
                self.profitability_score
                + self.growth_score
                + self.valuation_score
                + self.quality_score
            )
            / 4.0
        )

    @property
    def combined_score(self) -> float:
        return clamp((self.tech_score * 0.45) + (self.news_event_score * 0.25) + (self.fundamental_score * 0.30))

    @property
    def trigger_tags(self) -> list[str]:
        tags: list[str] = []
        if self.breakout_score >= 0.70:
            tags.append("breakout")
        if self.pullback_score >= 0.60:
            tags.append("pullback")
        if self.momentum_score >= 0.70:
            tags.append("momentum")
        if self.news_event_score >= 0.65:
            tags.append("event")
        return tags or ["watch"]

    @property
    def realtime_brief(self) -> str:
        if self.realtime_summary:
            return self.realtime_summary
        if self.realtime_headline:
            return self.realtime_headline
        return "T-0~T-3 realtime placeholder"

    @property
    def fundamental_brief(self) -> str:
        return (
            f"profitability={self.profitability_score:.2f}, growth={self.growth_score:.2f}, "
            f"valuation={self.valuation_score:.2f}, quality={self.quality_score:.2f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "industry": self.industry,
            "last_price": round(self.last_price, 4),
            "momentum_score": round(self.momentum_score, 4),
            "value_score": round(self.value_score, 4),
            "news_score": round(self.news_score, 4),
            "breakout_score": round(self.breakout_score, 4),
            "pullback_score": round(self.pullback_score, 4),
            "volatility_score": round(self.volatility_score, 4),
            "liquidity_score": round(self.liquidity_score, 4),
            "profitability_score": round(self.profitability_score, 4),
            "growth_score": round(self.growth_score, 4),
            "valuation_score": round(self.valuation_score, 4),
            "quality_score": round(self.quality_score, 4),
            "event_score": round(self.event_score, 4),
            "tech_score": round(self.tech_score, 4),
            "news_event_score": round(self.news_event_score, 4),
            "fundamental_score": round(self.fundamental_score, 4),
            "combined_score": round(self.combined_score, 4),
            "trigger_tags": list(self.trigger_tags),
            "realtime_headline": self.realtime_headline,
            "realtime_summary": self.realtime_summary,
        }

def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def normalize_token(value: Any, default: str) -> str:
    token = str(value or default).strip().upper().replace("-", "_").replace(" ", "_")
    return token or default


def load_account(snapshot: dict[str, Any]) -> AccountSnapshot:
    return AccountSnapshot.from_dict(snapshot.get("account", {}))


def load_positions(snapshot: dict[str, Any]) -> list[PositionSnapshot]:
    raw_positions = snapshot.get("positions") or snapshot.get("positions_prev") or []
    return [PositionSnapshot.from_dict(item) for item in raw_positions]


def load_watchlist(snapshot: dict[str, Any]) -> list[WatchlistCandidate]:
    fundamentals_map = {
        str(item["symbol"]): item for item in snapshot.get("fundamentals", []) if "symbol" in item
    }
    realtime_map = {
        str(item["symbol"]): item for item in snapshot.get("news_events", []) if "symbol" in item
    }
    raw_candidates = snapshot.get("universe") or snapshot.get("watchlist") or []
    candidates: list[WatchlistCandidate] = []
    for raw in raw_candidates:
        symbol = str(raw.get("symbol", ""))
        candidates.append(
            WatchlistCandidate.from_sources(
                raw=raw,
                fundamentals=fundamentals_map.get(symbol),
                realtime_info=realtime_map.get(symbol),
            )
        )
    return candidates


def build_symbol_map(items: list[dict[str, Any]], *, key: str = "symbol") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items if key in item}


def position_map(positions: list[PositionSnapshot]) -> dict[str, PositionSnapshot]:
    return {position.symbol: position for position in positions}


def watchlist_map(candidates: list[WatchlistCandidate]) -> dict[str, WatchlistCandidate]:
    return {candidate.symbol: candidate for candidate in candidates}


def compute_gross_exposure(positions: list[PositionSnapshot], total_equity: float) -> float:
    if total_equity <= 0:
        return 0.0
    return sum(position.current_weight(total_equity) for position in positions)


def compute_industry_exposure(positions: list[PositionSnapshot], total_equity: float) -> dict[str, float]:
    exposure: dict[str, float] = {}
    if total_equity <= 0:
        return exposure
    for position in positions:
        exposure[position.industry] = exposure.get(position.industry, 0.0) + position.current_weight(total_equity)
    return exposure


def derive_risk_mode(account: AccountSnapshot, config: dict[str, Any]) -> str:
    drawdown_protect_pct = float(config["risk"]["drawdown_protect_pct"])
    if account.portfolio_drawdown_pct >= drawdown_protect_pct:
        return RiskMode.RISK_OFF.value
    normalized = normalize_token(account.market_regime, RiskMode.NEUTRAL.value)
    if normalized in {RiskMode.RISK_ON.value, RiskMode.RISK_OFF.value}:
        return normalized
    return RiskMode.NEUTRAL.value


def regime_factor_for_risk_mode(config: dict[str, Any], risk_mode: str) -> float:
    if risk_mode == RiskMode.RISK_ON.value:
        return float(config["position"]["regime_factor_risk_on"])
    if risk_mode == RiskMode.RISK_OFF.value:
        return float(config["position"]["regime_factor_risk_off"])
    return float(config["position"]["regime_factor_neutral"])


def portfolio_cap_for_risk_mode(config: dict[str, Any], risk_mode: str) -> float:
    if risk_mode == RiskMode.RISK_ON.value:
        return float(config["position"]["portfolio_cap_risk_on"])
    if risk_mode == RiskMode.RISK_OFF.value:
        return float(config["position"]["portfolio_cap_risk_off"])
    return float(config["position"]["portfolio_cap_neutral"])


def resolve_reference_price(
    symbol: str,
    positions_by_symbol: dict[str, PositionSnapshot],
    watchlist_by_symbol: dict[str, WatchlistCandidate],
) -> float:
    if symbol in positions_by_symbol:
        return positions_by_symbol[symbol].last_price
    if symbol in watchlist_by_symbol:
        return watchlist_by_symbol[symbol].last_price
    return 0.0
