from __future__ import annotations

from pathlib import Path
import sys
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.pipeline.io import (
    DeciderStageInput,
    ExecutorArtifactView,
    ExecutorStageInput,
    ReporterArtifactView,
    ReporterStageInput,
    RiskGuardStageInput,
    SnapshotBundle,
)
from app.pipeline.outputs import (
    AIInsightRow,
    AnalystStageOutput,
    ExecutorStageOutput,
    HoldingActionRow,
    HoldingReviewStageOutput,
    MetricsSummary,
    NavRow,
    NewsSearchItemRow,
    NewsSearchView,
    OrderCandidateRow,
    PositionRow,
    PositionSnapshotRow,
    ReporterStageOutput,
    SelectorStageOutput,
    SimFillRow,
    TechCandidateRow,
)
from app.pipeline.results import StageResult


class SnapshotBundleTests(unittest.TestCase):
    def test_snapshot_bundle_uses_market_watchlist_and_keeps_query_precedence(self) -> None:
        payload = {
            "trade_date": "2026-03-10",
            "snapshot": {
                "watchlist": [{"symbol": "600000.SH"}],
                "selector_query": {"keyword": "白酒", "source": "snapshot"},
                "recent_events": [{"symbol": "600519.SH"}],
                "fundamentals": [{"symbol": "600519.SH"}],
            },
            "snapshot_market": {
                "watchlist": [{"symbol": "600519.SH"}],
                "selector_query": {"keyword": "ignored", "source": "candidate_pool"},
            },
        }

        bundle = SnapshotBundle.from_payload(payload)

        self.assertEqual(bundle.trade_date, "2026-03-10")
        self.assertEqual(bundle.watchlist, [{"symbol": "600519.SH"}])
        self.assertEqual(bundle.selector_query, {"keyword": "白酒", "source": "snapshot"})
        self.assertEqual(bundle.recent_events, [{"symbol": "600519.SH"}])
        self.assertEqual(bundle.fundamentals, [{"symbol": "600519.SH"}])


class RiskGuardStageInputTests(unittest.TestCase):
    def test_risk_guard_stage_input_defaults_are_stable(self) -> None:
        stage_input = RiskGuardStageInput.from_payload({})

        self.assertEqual(stage_input.portfolio.account, {})
        self.assertEqual(stage_input.portfolio.positions_prev, [])
        self.assertEqual(stage_input.portfolio.risk_mode, "NEUTRAL")
        self.assertEqual(stage_input.orders_candidate, [])
        self.assertEqual(stage_input.tech_candidates, [])


class ExecutorStageInputTests(unittest.TestCase):
    def test_execution_watchlist_prefers_selector_watchlist(self) -> None:
        payload = {
            "selector_watchlist": [{"symbol": "300750.SZ"}],
            "snapshot": {"watchlist": [{"symbol": "600519.SH"}]},
            "snapshot_market": {"watchlist": [{"symbol": "000001.SZ"}]},
        }

        stage_input = ExecutorStageInput.from_payload(payload)

        self.assertEqual(stage_input.execution_watchlist, [{"symbol": "300750.SZ"}])

    def test_execution_watchlist_falls_back_to_effective_snapshot_watchlist(self) -> None:
        payload = {
            "snapshot": {"watchlist": [{"symbol": "600519.SH"}]},
            "snapshot_market": {"watchlist": [{"symbol": "000001.SZ"}]},
        }

        stage_input = ExecutorStageInput.from_payload(payload)

        self.assertEqual(stage_input.execution_watchlist, [{"symbol": "000001.SZ"}])


class DeciderStageInputTests(unittest.TestCase):
    def test_candidate_price_rows_prefer_selector_watchlist(self) -> None:
        payload = {
            "selector_watchlist": [{"symbol": "300750.SZ"}],
            "snapshot_market": {"watchlist": [{"symbol": "000001.SZ"}]},
        }

        stage_input = DeciderStageInput.from_payload(payload)

        self.assertEqual(stage_input.candidate_price_rows, [{"symbol": "300750.SZ"}])


class ReporterStageInputTests(unittest.TestCase):
    def test_nav_row_returns_latest_nav_entry(self) -> None:
        payload = {
            "nav": [
                {"trade_date": "2026-03-10", "total_equity": 100000},
                {"trade_date": "2026-03-11", "total_equity": 101500},
            ]
        }

        stage_input = ReporterStageInput.from_payload(payload)

        self.assertEqual(stage_input.nav_row, {"trade_date": "2026-03-11", "total_equity": 101500})


class ArtifactViewTests(unittest.TestCase):
    def test_executor_artifact_view_coerces_rows(self) -> None:
        view = ExecutorArtifactView.from_stage_outputs(
            {
                "sim_fill": [{"order_id": "A1"}],
                "positions": [{"symbol": "600519.SH"}],
                "nav": [{"trade_date": "2026-03-10"}],
            }
        )

        self.assertEqual(view.sim_fill, [{"order_id": "A1"}])
        self.assertEqual(view.positions, [{"symbol": "600519.SH"}])
        self.assertEqual(view.nav, [{"trade_date": "2026-03-10"}])

    def test_reporter_artifact_view_defaults_are_stable(self) -> None:
        view = ReporterArtifactView.from_stage_outputs({"metrics": [], "risk_report_markdown": None})

        self.assertEqual(view.metrics, {})
        self.assertEqual(view.risk_report_markdown, "")


class StageOutputModelTests(unittest.TestCase):
    def test_stage_result_coerces_output_model_to_updates_dict(self) -> None:
        result = StageResult(
            updates=SelectorStageOutput(
                tech_candidates=[
                    TechCandidateRow(
                        trade_date="2026-03-10",
                        symbol="600519.SH",
                        name="贵州茅台",
                        sector="Consumer",
                        board="MAIN",
                        last_price=1642.0,
                        prev_close=1635.0,
                        upper_limit=1798.5,
                        lower_limit=1471.5,
                        rule_pass=True,
                        tech_score=0.81,
                        momentum_score=0.82,
                        breakout_score=0.79,
                        liquidity_score=0.86,
                        turnover_rate=0.022,
                        turnover_rate_proxy=0.0,
                        relative_volume=1.1,
                        relative_amount=0.0,
                        amount=1100000000.0,
                        daily_pct_change=0.0043,
                        return_5d=0.0,
                        return_20d=0.0,
                        ma20=0.0,
                        ma60=0.0,
                        price_vs_ma20=0.0,
                        price_vs_20d_high=0.0,
                        volatility_20d=0.0,
                        near_upper_limit=False,
                        is_st=False,
                        suspended=False,
                        list_days=8000,
                        market_data_source="snapshot",
                        technical_flags="",
                        technical_summary="",
                        trigger_tags="momentum|breakout",
                    )
                ],
                selector_watchlist=[{"symbol": "600519.SH"}],
                selector_source="candidate_pool",
                stock_screen_result={},
                selector_failed=False,
            ),
            stage_note="selector_test",
        )

        self.assertIsInstance(result.updates, dict)
        self.assertEqual(result.updates["selector_source"], "candidate_pool")
        self.assertEqual(result.updates["tech_candidates"][0]["name"], "贵州茅台")
        self.assertEqual(result.stage_note, "selector_test")

    def test_stage_result_accepts_output_model(self) -> None:
        result = StageResult(
            updates=ReporterStageOutput(
                metrics=MetricsSummary(
                    run_id="demo-run",
                    trade_date="2026-03-10",
                    daily_return=0.01,
                    cum_return=0.05,
                    max_drawdown=0.02,
                    trading_fees=123.0,
                    sharpe_ratio=1.5,
                    win_rate=0.6,
                    risk_intercept_count=2,
                    filled_order_count=3,
                    accepted_order_count=4,
                    limit_no_fill_count=1,
                    total_buy_orders=2,
                    total_sell_orders=1,
                    selector_failed=False,
                    risk_mode="NEUTRAL",
                ),
                risk_report_markdown="# report",
            ),
        )

        self.assertEqual(result.updates["metrics"]["trade_date"], "2026-03-10")
        self.assertEqual(result.updates["metrics"]["filled_order_count"], 3)
        self.assertEqual(result.updates["risk_report_markdown"], "# report")

    def test_holding_review_output_serializes_row_models(self) -> None:
        result = StageResult(
            updates=HoldingReviewStageOutput(
                account={"cash": 100000.0},
                risk_mode="NEUTRAL",
                positions_prev=[
                    PositionSnapshotRow(
                        trade_date="2026-03-10",
                        symbol="600519.SH",
                        name="贵州茅台",
                        sector="Consumer",
                        board="MAIN",
                        quantity=100.0,
                        available_quantity=100.0,
                        avg_cost=1600.0,
                        prev_close=1635.0,
                        last_price=1642.0,
                        upper_limit=1798.5,
                        lower_limit=1471.5,
                        market_value=164200.0,
                        current_weight=0.15,
                        unrealized_pnl_pct=0.02625,
                        is_st=False,
                        suspended=False,
                        list_days=8000.0,
                        last_trade_date="2026-03-09",
                        t_plus_one_locked=False,
                        event_score=0.72,
                    )
                ],
                positions=[],
                holding_actions=[
                    HoldingActionRow(
                        trade_date="2026-03-10",
                        symbol="600519.SH",
                        name="贵州茅台",
                        sector="Consumer",
                        board="MAIN",
                        quantity=100.0,
                        available_quantity=100.0,
                        avg_cost=1600.0,
                        prev_close=1635.0,
                        last_price=1642.0,
                        upper_limit=1798.5,
                        lower_limit=1471.5,
                        current_weight=0.15,
                        action_today="HOLD",
                        target_weight=0.15,
                        stop_loss=1472.0,
                        take_profit=1840.0,
                        risk_level="LOW",
                        is_st=False,
                        suspended=False,
                        list_days=8000.0,
                        reason="trend_intact",
                        last_trade_date="2026-03-09",
                        t_plus_one_locked=False,
                    )
                ],
            ),
        )

        self.assertEqual(result.updates["account"]["cash"], 100000.0)
        self.assertEqual(result.updates["positions_prev"][0]["symbol"], "600519.SH")
        self.assertEqual(result.updates["holding_actions"][0]["action_today"], "HOLD")

    def test_executor_output_serializes_core_rows(self) -> None:
        result = StageResult(
            updates=ExecutorStageOutput(
                sim_fill=[
                    SimFillRow(
                        trade_date="2026-03-10",
                        order_id="O1",
                        symbol="600519.SH",
                        name="贵州茅台",
                        board="MAIN",
                        action="BUILD",
                        planned_price=1642.0,
                        fill_price=1643.0,
                        price_deviation_bps=6.09,
                        quantity=100.0,
                        filled_amount=164300.0,
                        commission=50.0,
                        stamp_duty=0.0,
                        transfer_fee=0.0,
                        total_fee=50.0,
                        status="FILLED",
                        note="build_filled",
                    )
                ],
                positions=[
                    PositionRow(
                        trade_date="2026-03-10",
                        symbol="600519.SH",
                        name="贵州茅台",
                        sector="Consumer",
                        board="MAIN",
                        quantity=100.0,
                        available_quantity=100.0,
                        avg_cost=1643.5,
                        prev_close=1635.0,
                        last_price=1643.0,
                        upper_limit=1798.5,
                        lower_limit=1471.5,
                        market_value=164300.0,
                        weight=0.15,
                        unrealized_pnl_pct=-0.0003,
                        is_st=False,
                        suspended=False,
                        last_trade_date="2026-03-10",
                    )
                ],
                nav=[
                    NavRow(
                        trade_date="2026-03-10",
                        cash=850000.0,
                        market_value=164300.0,
                        total_equity=1014300.0,
                        trading_fees=50.0,
                        daily_return=0.01,
                        cum_return=0.02,
                        max_drawdown=0.03,
                        filled_order_count=1,
                    )
                ],
                executor_failed=False,
            ),
        )

        self.assertEqual(result.updates["sim_fill"][0]["status"], "FILLED")
        self.assertEqual(result.updates["positions"][0]["weight"], 0.15)
        self.assertEqual(result.updates["nav"][0]["filled_order_count"], 1)

    def test_analyst_output_serializes_research_models(self) -> None:
        result = StageResult(
            updates=AnalystStageOutput(
                ai_insights=[
                    AIInsightRow(
                        trade_date="2026-03-10",
                        symbol="002371.SZ",
                        name="北方华创",
                        sector="Semis",
                        board="MAIN",
                        action_hint="BUILD",
                        confidence=0.78,
                        tech_score=0.81,
                        market_technical_score=0.80,
                        news_event_score=0.76,
                        fundamental_score=0.74,
                        combined_score=0.78,
                        market_data_source="snapshot",
                        technical_summary="trend strong",
                        thesis="景气持续",
                        risk_flags="valuation_watch",
                    )
                ],
                analyst_news_search={
                    "002371.SZ": NewsSearchView(
                        source="eastmoney_news_search",
                        query="北方华创(002371) 资讯",
                        count=2,
                        news_search_score=0.66,
                        summary="半导体景气延续",
                        items=[
                            NewsSearchItemRow(
                                title="半导体景气延续",
                                date="2026-03-10",
                                information_type="news",
                                jump_url="https://example.com/news/1",
                                excerpt="订单景气度维持高位",
                            )
                        ],
                    )
                },
            ),
        )

        self.assertEqual(result.updates["ai_insights"][0]["action_hint"], "BUILD")
        self.assertEqual(result.updates["analyst_news_search"]["002371.SZ"]["items"][0]["title"], "半导体景气延续")


if __name__ == "__main__":
    unittest.main()
