from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.components import executor, risk_guard
from app.pipeline import RunContext
from app.pipeline.outputs import AIInsightRow
from app.pipeline.stages import validate_stage_updates


def _build_ctx(run_id: str, config: dict[str, object]) -> RunContext:
    root = Path(tempfile.mkdtemp())
    return RunContext(
        run_id=run_id,
        trade_date="2026-03-10",
        config=config,
        input_path=root / "input.json",
        output_root=root,
        output_dir=root / "outputs" / run_id,
    )


class FailurePathTests(unittest.TestCase):
    def test_risk_guard_fallback_marks_failure_and_reason(self) -> None:
        ctx = _build_ctx(
            "risk-fallback",
            {
                "risk": {"mode_caps": {"neutral": 0.50}},
                "risk_rules": {"single_stock_cap": {"value": 0.12}},
            },
        )
        payload = {
            "account": {
                "cash": 100000.0,
                "total_equity": 100000.0,
                "prev_total_equity": 100000.0,
                "initial_equity": 100000.0,
                "portfolio_drawdown_pct": 0.0,
            },
            "positions_prev": [],
            "risk_mode": "NEUTRAL",
            "orders_candidate": [
                {
                    "trade_date": "2026-03-10",
                    "order_id": "O1",
                    "symbol": "002371.SZ",
                    "name": "北方华创",
                    "sector": "Semis",
                    "board": "MAIN",
                    "action": "BUILD",
                    "w_ai": 0.12,
                    "w_candidate": 0.12,
                    "target_weight": 0.12,
                    "entry_price": 428.0,
                    "stop_loss_price": 393.76,
                    "take_profit_price": 492.2,
                    "reduce_price": 466.52,
                    "exit_price": 393.76,
                    "reason": "build_setup_confirmed",
                    "confidence": 0.81,
                }
            ],
            "tech_candidates": [],
        }

        with patch("app.components.risk_guard._build_trade_plan", side_effect=RuntimeError("boom")):
            result = risk_guard.run(ctx, payload)

        self.assertTrue(result.updates["risk_guard_failed"])
        self.assertEqual(result.updates["trade_plan"][0]["status"], "REJECTED")
        self.assertIn("risk_guard_fallback:boom", result.updates["trade_plan"][0]["cap_hit_reason"])
        self.assertIn("risk_guard_fallback", result.stage_note)

    def test_executor_fallback_marks_skipped_rows(self) -> None:
        ctx = _build_ctx("executor-fallback", {})
        payload = {
            "account": {
                "cash": 100000.0,
                "total_equity": 100000.0,
                "prev_total_equity": 100000.0,
                "initial_equity": 100000.0,
                "portfolio_drawdown_pct": 0.0,
            },
            "positions_prev": [],
            "risk_mode": "NEUTRAL",
            "trade_plan": [
                {
                    "trade_date": "2026-03-10",
                    "order_id": "O1",
                    "symbol": "002371.SZ",
                    "name": "北方华创",
                    "sector": "Semis",
                    "board": "MAIN",
                    "action": "BUILD",
                    "w_ai": 0.12,
                    "w_candidate": 0.12,
                    "target_weight": 0.12,
                    "w_final": 0.12,
                    "status": "ACCEPTED",
                    "cap_hit_reason": "",
                    "risk_mode": "NEUTRAL",
                    "entry_price_final": 428.0,
                    "stop_loss_price_final": 393.76,
                    "take_profit_price_final": 492.2,
                    "reduce_price_final": 466.52,
                    "exit_price_final": 393.76,
                    "reason": "build_setup_confirmed",
                }
            ],
        }

        with patch("app.components.executor._execute_trade_plan", side_effect=RuntimeError("boom")):
            result = executor.run(ctx, payload)

        self.assertTrue(result.updates["executor_failed"])
        self.assertEqual(result.updates["sim_fill"][0]["status"], "SKIPPED")
        self.assertIn("executor_failed:boom", result.updates["sim_fill"][0]["note"])
        self.assertIn("executor_fallback", result.stage_note)

    def test_validate_stage_updates_rejects_nested_analyst_contract_drift(self) -> None:
        ai_insight = AIInsightRow(
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
        ).to_dict()

        with self.assertRaises(ValueError) as context:
            validate_stage_updates(
                "analyst",
                {
                    "ai_insights": [ai_insight],
                    "analyst_news_search": {
                        "002371.SZ": {
                            "source": "eastmoney_news_search",
                            "query": "北方华创(002371) 资讯",
                            "count": 2,
                            "news_search_score": 0.66,
                            "summary": "半导体景气延续",
                        }
                    },
                },
            )

        self.assertIn("items", str(context.exception))


if __name__ == "__main__":
    unittest.main()
