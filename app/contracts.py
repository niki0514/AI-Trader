from __future__ import annotations

from app.pipeline.outputs import (
    AIInsightRow,
    HoldingActionRow,
    NavRow,
    OrderCandidateRow,
    PositionRow,
    SimFillRow,
    TechCandidateRow,
    TradePlanRow,
)

BUY_LIKE_ACTIONS = {"BUILD", "ADD"}
SELL_LIKE_ACTIONS = {"REDUCE", "EXIT"}

HOLDING_ACTION_FIELDS = HoldingActionRow.field_names()
TECH_CANDIDATE_FIELDS = TechCandidateRow.field_names()
AI_INSIGHT_FIELDS = AIInsightRow.field_names()
ORDER_CANDIDATE_FIELDS = OrderCandidateRow.field_names()
TRADE_PLAN_FIELDS = TradePlanRow.field_names()
SIM_FILL_FIELDS = SimFillRow.field_names()
POSITION_FIELDS = PositionRow.field_names()
NAV_FIELDS = NavRow.field_names()
