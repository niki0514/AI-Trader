from __future__ import annotations

from enum import Enum


class TradeAction(str, Enum):
    BUILD = "BUILD"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class PlanStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RiskMode(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


class FillStatus(str, Enum):
    FILLED = "FILLED"
    SKIPPED = "SKIPPED"
    REVIEW = "REVIEW"
