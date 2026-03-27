from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.pipeline import RunContext
from app.runner import run_pipeline


def _build_test_config() -> dict[str, object]:
    return {
        "pipeline": {"preset": "full"},
        "market_data": {
            "provider": "wind",
            "wind": {
                "enabled": False,
                "strict": False,
                "history_lookback_days": 120,
                "min_history_days": 30,
                "prefer_source_prices": True,
                "connect_timeout_seconds": 10,
            },
        },
        "news_search": {
            "enabled": False,
            "default_size": 8,
        },
        "selection": {
            "source": "candidate_pool",
            "top_n": 0,
            "rule_filter": "minimal",
            "tech_score_floor": 0.64,
            "liquidity_score_floor": 0.50,
            "momentum_weight": 0.30,
            "breakout_weight": 0.20,
            "liquidity_weight": 0.15,
        },
        "holding": {
            "stop_loss_pct": 0.08,
            "take_profit_pct": 0.15,
        },
        "decision": {
            "entry_buffer_bps": 8,
        },
        "risk": {
            "default_mode": "NEUTRAL",
            "mode_caps": {
                "risk_on": 0.70,
                "neutral": 0.50,
                "risk_off": 0.30,
            },
        },
        "risk_rules": {
            "single_stock_cap": {"enabled": True, "value": 0.12},
            "industry_cap": {"enabled": True, "value": 0.25},
            "liquidity_cap": {"enabled": True, "value": 0.10},
            "t_plus_one": {"enabled": True},
            "drawdown_guard": {
                "enabled": True,
                "block_build_add_pct": 0.10,
                "cap_multiplier": 0.70,
            },
        },
        "execution": {
            "slippage_bps": 8,
            "allow_fractional_shares": False,
        },
        "a_share": {
            "trading": {
                "default_lot_size": 100,
                "price_tick": 0.01,
                "lot_size_by_board": {
                    "main": 100,
                    "chinext": 100,
                    "star": 100,
                    "bse": 100,
                },
            },
            "boards": {
                "main_price_limit_pct": 0.10,
                "main_risk_warning_price_limit_pct": 0.05,
                "chinext_price_limit_pct": 0.20,
                "star_price_limit_pct": 0.20,
                "bse_price_limit_pct": 0.30,
                "new_listing_unlimited_days": {
                    "main": 5,
                    "chinext": 5,
                    "star": 5,
                    "bse": 1,
                },
            },
            "fees": {
                "commission_rate": 0.0003,
                "min_commission": 5.0,
                "stamp_duty_rate_sell": 0.0005,
                "transfer_fee_rate": 0.00001,
            },
            "selection": {
                "min_turnover_rate": 0.02,
                "preferred_turnover_rate": 0.06,
                "min_relative_volume": 1.0,
                "min_amount": 300000000,
                "turnover_weight": 0.15,
                "relative_volume_weight": 0.10,
                "amount_weight": 0.10,
                "near_limit_up_guard_pct": 0.985,
                "near_limit_up_penalty": 0.18,
            },
            "risk": {
                "buy_reject_if_st": True,
                "buy_reject_if_suspended": True,
                "buy_reject_if_limit_up": True,
                "min_listing_days": 60,
                "min_amount": 300000000,
                "min_turnover_rate": 0.015,
                "board_caps": {
                    "main": 0.50,
                    "chinext": 0.20,
                    "star": 0.15,
                    "bse": 0.08,
                },
            },
        },
        "llm": {
            "provider": "gmn",
            "enable_live": True,
        },
        "degrade": {
            "disable_selector": False,
            "disable_executor": False,
        },
    }


def _load_candidate_pool_snapshot() -> dict[str, object]:
    path = BACKEND_DIR / "examples" / "input" / "candidate_pool_snapshot.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_context(root: Path, run_id: str, config: dict[str, object]) -> RunContext:
    return RunContext(
        run_id=run_id,
        trade_date="2026-03-10",
        config=config,
        input_path=root / "input.json",
        output_root=root,
        output_dir=root / "outputs" / run_id,
    )


def _mock_holding_actions(_config: dict[str, object], _prompt: str) -> dict[str, object]:
    return {
        "decisions": [
            {
                "symbol": "600036.SH",
                "action_today": "HOLD",
                "target_weight": 0.10,
                "risk_level": "LOW",
                "reason": "trend_intact",
            }
        ]
    }


def _mock_analyst(_config: dict[str, object], _prompt: str) -> dict[str, object]:
    return {
        "action_hint": "BUILD",
        "confidence": 0.83,
        "risk_flags": ["watch_valuation"],
        "thesis": "trend_and_event_support",
    }


def _mock_decider(_config: dict[str, object], _prompt: str) -> dict[str, object]:
    return {
        "action": "BUILD",
        "target_weight": 0.12,
        "confidence": 0.81,
        "reason": "build_setup_confirmed",
    }


def _mock_reporter(_config: dict[str, object], _prompt: str) -> str:
    return "# Daily Report\n\nExecution stable."


class PipelineRunnerE2ETests(unittest.TestCase):
    def test_full_preset_runs_end_to_end_with_managed_artifacts(self) -> None:
        config = _build_test_config()
        snapshot = _load_candidate_pool_snapshot()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = _build_run_context(root, "e2e-full", config)
            payload = {
                "run_id": "e2e-full",
                "snapshot": snapshot,
            }

            with patch("app.components.update_holding_actions.request_agent_json", side_effect=_mock_holding_actions), patch(
                "app.components.analyst.request_agent_json",
                side_effect=_mock_analyst,
            ), patch("app.components.decider.request_agent_json", side_effect=_mock_decider), patch(
                "app.components.reporter.request_agent_text",
                side_effect=_mock_reporter,
            ):
                result = run_pipeline(ctx, payload)
            self.assertEqual(
                result["pipeline_stages"],
                [
                    "update_holding_actions",
                    "selector",
                    "analyst",
                    "decider",
                    "risk_guard",
                    "executor",
                    "reporter",
                ],
            )
            self.assertEqual(result["selector_source"], "candidate_pool")
            self.assertEqual(len(result["tech_candidates"]), 3)
            self.assertEqual(len(result["ai_insights"]), 3)
            self.assertFalse(result["risk_guard_failed"])
            self.assertFalse(result["executor_failed"])
            self.assertGreaterEqual(result["metrics"]["filled_order_count"], 1)
            self.assertIn("report_files", result)
            self.assertIn("pipeline", result["stage_notes"])
            self.assertTrue(any(row["status"] == "FILLED" for row in result["sim_fill"]))

            self.assertTrue(ctx.artifact_path("holding_actions_t.csv").exists())
            self.assertTrue(ctx.artifact_path("tech_candidates_t.csv").exists())
            self.assertTrue(ctx.artifact_path("ai_insights_t.csv").exists())
            self.assertTrue(ctx.artifact_path("orders_candidate_t.csv").exists())
            self.assertTrue(ctx.artifact_path("trade_plan_t.csv").exists())
            self.assertTrue(ctx.artifact_path("sim_fill_t.csv").exists())
            self.assertTrue(ctx.artifact_path("positions_t.csv").exists())
            self.assertTrue(ctx.artifact_path("nav_t.csv").exists())
            self.assertTrue(Path(result["report_files"]["metrics_t.json"]).exists())
            self.assertTrue(Path(result["report_files"]["risk_report_t.md"]).exists())

            self.assertTrue(ctx.stage_output_path(1, "update_holding_actions").exists())
            self.assertTrue(ctx.stage_output_path(2, "selector").exists())
            self.assertTrue(ctx.stage_output_path(3, "analyst").exists())
            self.assertTrue(ctx.stage_output_path(4, "decider").exists())
            self.assertTrue(ctx.stage_output_path(5, "risk_guard").exists())
            self.assertTrue(ctx.stage_output_path(6, "executor").exists())
            self.assertTrue(ctx.stage_output_path(7, "reporter").exists())

            reporter_stage_payload = json.loads(ctx.stage_output_path(7, "reporter").read_text(encoding="utf-8"))
            self.assertEqual(reporter_stage_payload["stage_name"], "reporter")
            self.assertIn("outputs", reporter_stage_payload)
            self.assertIn("artifacts", reporter_stage_payload)
            self.assertIn("metrics", reporter_stage_payload["outputs"])
            self.assertIn("report_files", reporter_stage_payload["artifacts"])
            self.assertEqual(reporter_stage_payload["inputs"]["trade_date"], "2026-03-10")
            self.assertEqual(reporter_stage_payload["inputs"]["run_id"], "e2e-full")
            self.assertNotIn("metrics", reporter_stage_payload["inputs"])
            self.assertNotIn("sim_fill", reporter_stage_payload["outputs"])

    def test_research_preset_runs_selector_and_analyst_only(self) -> None:
        config = _build_test_config()
        snapshot = _load_candidate_pool_snapshot()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = _build_run_context(root, "e2e-research", config)
            payload = {
                "run_id": "e2e-research",
                "pipeline_preset": "research",
                "snapshot": snapshot,
            }

            with patch("app.components.analyst.request_agent_json", side_effect=_mock_analyst):
                result = run_pipeline(ctx, payload)
            self.assertEqual(result["pipeline_stages"], ["selector", "analyst"])
            self.assertEqual(result["selector_source"], "candidate_pool")
            self.assertEqual(len(result["tech_candidates"]), 3)
            self.assertEqual(len(result["ai_insights"]), 3)
            self.assertEqual(result["analyst_news_search"], {})
            self.assertNotIn("orders_candidate", result)
            self.assertNotIn("metrics", result)
            self.assertNotIn("report_files", result)

            self.assertTrue(ctx.artifact_path("tech_candidates_t.csv").exists())
            self.assertTrue(ctx.artifact_path("ai_insights_t.csv").exists())
            self.assertFalse(ctx.artifact_path("metrics_t.json").exists())
            self.assertTrue(ctx.stage_output_path(1, "selector").exists())
            self.assertTrue(ctx.stage_output_path(2, "analyst").exists())

            analyst_stage_payload = json.loads(ctx.stage_output_path(2, "analyst").read_text(encoding="utf-8"))
            self.assertEqual(analyst_stage_payload["pipeline_stages"], ["selector", "analyst"])
            self.assertEqual(analyst_stage_payload["stage_name"], "analyst")
            self.assertEqual(analyst_stage_payload["inputs"]["trade_date"], "2026-03-10")
            self.assertIn("snapshot_market", analyst_stage_payload["inputs"])
            self.assertIn("ai_insights", analyst_stage_payload["outputs"])
            self.assertEqual(analyst_stage_payload["artifacts"], {})
            self.assertNotIn("ai_insights", analyst_stage_payload["inputs"])


if __name__ == "__main__":
    unittest.main()
