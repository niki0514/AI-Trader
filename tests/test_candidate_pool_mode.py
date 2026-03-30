from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.server import TraderApiService
from app.components import analyst, selector
from app.pipeline.artifacts import export_stage_artifacts
from app.pipeline import RunContext
from app.pipeline.stages import (
    resolve_pipeline_stage_names,
    validate_artifact_updates,
    validate_pipeline_sequence,
    validate_stage_payload,
    validate_stage_updates,
)


class CandidatePoolModeTests(unittest.TestCase):
    def test_selector_candidate_pool_keeps_full_watchlist_when_top_n_is_zero(self) -> None:
        config = {
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
            "a_share": {
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
                "trading": {
                    "price_tick": 0.01,
                },
            },
            "degrade": {
                "disable_selector": False,
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = RunContext(
                run_id="candidate-pool-test",
                trade_date="2026-03-10",
                config=config,
                input_path=root / "input.json",
                output_root=root,
                output_dir=root / "outputs" / "candidate-pool-test",
            )
            payload = {
                "snapshot": {
                    "watchlist": [
                        {
                            "symbol": "600000.SH",
                            "name": "浦发银行",
                            "sector": "Financials",
                            "prev_close": 10.0,
                            "last_price": 10.2,
                            "momentum_score": 0.51,
                            "breakout_score": 0.48,
                            "liquidity_score": 0.40,
                            "turnover_rate": 0.001,
                            "relative_volume": 0.50,
                            "amount": 5000000,
                            "list_days": 8000,
                            "suspended": False,
                            "is_st": False,
                        },
                        {
                            "symbol": "600519.SH",
                            "name": "贵州茅台",
                            "sector": "Consumer",
                            "prev_close": 1635.0,
                            "last_price": 1642.0,
                            "momentum_score": 0.82,
                            "breakout_score": 0.79,
                            "liquidity_score": 0.86,
                            "turnover_rate": 0.022,
                            "relative_volume": 1.10,
                            "amount": 1100000000,
                            "list_days": 8000,
                            "suspended": False,
                            "is_st": False,
                        },
                    ]
                }
            }

            result = selector.run(ctx, payload)

        self.assertEqual(result.updates["selector_source"], "candidate_pool")
        self.assertEqual(len(result.updates["tech_candidates"]), 2)
        self.assertTrue(all(bool(row["rule_pass"]) for row in result.updates["tech_candidates"]))
        self.assertEqual(result.updates["tech_candidates"][0]["symbol"], "600519.SH")

    def test_analyst_skips_news_search_when_disabled(self) -> None:
        ctx = SimpleNamespace(
            config={"news_search": {"enabled": False}},
            output_dir=Path("/tmp/unused-output-dir"),
            trade_date="2026-03-10",
        )

        result = analyst._load_candidate_news_views(  # type: ignore[attr-defined]
            ctx=ctx,
            candidates=[{"symbol": "600519.SH", "name": "贵州茅台"}],
        )

        self.assertEqual(result, {})


class InlineSnapshotApiTests(unittest.TestCase):
    def test_run_daily_job_accepts_inline_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "pipeline.yaml"
            config_path.write_text("pipeline:\n  name: inline-test\n", encoding="utf-8")

            service = TraderApiService(
                project_root=PROJECT_ROOT,
                output_root=root / "outputs",
                default_config_path=config_path,
                default_input_path=root / "missing-input.json",
            )

            captured: dict[str, object] = {}

            def fake_run_pipeline(ctx: RunContext, payload: dict[str, object]) -> dict[str, object]:
                captured["trade_date"] = ctx.trade_date
                captured["snapshot"] = payload["snapshot"]
                captured["input_file"] = payload["input_file"]
                ctx.ensure_output_dirs()
                return {
                    "run_id": ctx.run_id,
                    "trade_date": ctx.trade_date,
                    "pipeline_stages": ["update_holding_actions", "selector"],
                    "stage_notes": {"pipeline": "update_holding_actions,selector"},
                    "snapshot": payload["snapshot"],
                    "metrics": {"trade_date": ctx.trade_date},
                    "report_files": {},
                }

            with patch("app.api.server.run_pipeline", side_effect=fake_run_pipeline):
                status, response = service.run_daily_job(
                    {
                        "run_id": "inline-demo",
                        "trade_date": "2026-03-11",
                        "snapshot": {
                            "account": {"cash": 100000, "total_equity": 100000},
                            "positions": [],
                            "watchlist": [],
                        },
                    }
                )
            response_payload = response.to_dict()

            self.assertEqual(status, 200)
            self.assertEqual(response_payload["trade_date"], "2026-03-11")
            self.assertEqual(captured["input_file"], "<inline_snapshot>")
            self.assertEqual(captured["trade_date"], "2026-03-11")
            self.assertEqual(response_payload["pipeline_stages"], ["update_holding_actions", "selector"])
            self.assertIn("pipeline", response_payload["stage_notes"])

            snapshot = captured["snapshot"]
            self.assertIsInstance(snapshot, dict)
            self.assertEqual(snapshot["trade_date"], "2026-03-11")

            final_payload_path = Path(response_payload["output_dir"]) / "final_payload.json"
            final_payload = json.loads(final_payload_path.read_text(encoding="utf-8"))
            self.assertEqual(final_payload["snapshot"]["trade_date"], "2026-03-11")

    def test_run_daily_job_passes_pipeline_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "pipeline.yaml"
            config_path.write_text("pipeline:\n  preset: full\n", encoding="utf-8")

            service = TraderApiService(
                project_root=PROJECT_ROOT,
                output_root=root / "outputs",
                default_config_path=config_path,
                default_input_path=root / "missing-input.json",
            )

            captured: dict[str, object] = {}

            def fake_run_pipeline(ctx: RunContext, payload: dict[str, object]) -> dict[str, object]:
                captured["pipeline_preset"] = payload.get("pipeline_preset")
                captured["pipeline_stages"] = payload.get("pipeline_stages")
                ctx.ensure_output_dirs()
                return {
                    "run_id": ctx.run_id,
                    "trade_date": ctx.trade_date,
                    "snapshot": payload["snapshot"],
                    "metrics": {"trade_date": ctx.trade_date},
                    "report_files": {},
                }

            with patch("app.api.server.run_pipeline", side_effect=fake_run_pipeline):
                status, _response = service.run_daily_job(
                    {
                        "run_id": "planning-demo",
                        "pipeline_preset": "planning",
                        "pipeline_stages": ["update_holding_actions", "selector"],
                        "snapshot": {
                            "trade_date": "2026-03-11",
                            "account": {"cash": 100000, "total_equity": 100000},
                            "positions": [],
                            "watchlist": [],
                        },
                    }
                )

            self.assertEqual(status, 200)
            self.assertEqual(captured["pipeline_preset"], "planning")
            self.assertEqual(captured["pipeline_stages"], ["update_holding_actions", "selector"])

    def test_run_daily_job_generates_default_run_id_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "pipeline.yaml"
            config_path.write_text("pipeline:\n  preset: full\n", encoding="utf-8")

            service = TraderApiService(
                project_root=PROJECT_ROOT,
                output_root=root / "outputs",
                default_config_path=config_path,
                default_input_path=root / "missing-input.json",
            )

            def fake_run_pipeline(ctx: RunContext, payload: dict[str, object]) -> dict[str, object]:
                ctx.ensure_output_dirs()
                return {
                    "run_id": ctx.run_id,
                    "trade_date": ctx.trade_date,
                    "snapshot": payload["snapshot"],
                    "pipeline_stages": ["selector"],
                    "stage_notes": {},
                    "metrics": {},
                    "report_files": {},
                }

            with patch("app.api.server.run_pipeline", side_effect=fake_run_pipeline):
                status, response = service.run_daily_job(
                    {
                        "snapshot": {
                            "trade_date": "2026-03-11",
                            "account": {"cash": 100000, "total_equity": 100000},
                            "positions": [],
                            "watchlist": [],
                        },
                    }
                )
            response_payload = response.to_dict()

            self.assertEqual(status, 200)
            self.assertTrue(response_payload["run_id"].startswith("single-day-20260311-"))
            self.assertEqual(response_payload["job_id"], response_payload["run_id"])


class PipelineCompositionTests(unittest.TestCase):
    def test_resolve_pipeline_stage_names_uses_canonical_preset_and_override_fields(self) -> None:
        config = {"pipeline": {"preset": "planning"}}
        self.assertEqual(
            resolve_pipeline_stage_names(config),
            ("update_holding_actions", "selector", "analyst", "decider", "risk_guard"),
        )
        self.assertEqual(
            resolve_pipeline_stage_names(config, overrides={"pipeline_stages": ["selector", "analyst"]}),
            ("selector", "analyst"),
        )

    def test_resolve_pipeline_stage_names_rejects_legacy_string_override(self) -> None:
        with self.assertRaises(ValueError) as context:
            resolve_pipeline_stage_names({"pipeline": {"preset": "planning"}}, overrides={"pipeline_stages": "selector,analyst"})

        self.assertIn("must be an array", str(context.exception))

    def test_validate_pipeline_sequence_rejects_missing_dependencies(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_pipeline_sequence(("decider",), initial_payload={"snapshot": {}, "trade_date": "2026-03-10"})
        self.assertIn("missing required inputs", str(context.exception))

    def test_validate_pipeline_sequence_requires_executor_portfolio_state(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_pipeline_sequence(("executor",), initial_payload={"trade_plan": []})
        self.assertIn("missing required inputs", str(context.exception))

    def test_validate_stage_updates_rejects_undeclared_outputs(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_stage_updates("selector", {"tech_candidates": [], "stage_notes": {}})
        self.assertIn("produced undeclared outputs", str(context.exception))

    def test_validate_stage_updates_rejects_invalid_output_shape(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_stage_updates(
                "selector",
                {
                    "tech_candidates": [],
                    "selector_watchlist": [],
                    "selector_source": [],
                    "stock_screen_result": {},
                    "selector_failed": False,
                },
            )
        self.assertIn("expects 'selector_source' to be a string", str(context.exception))

    def test_validate_stage_payload_rejects_invalid_shape(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_stage_payload("executor", {"trade_plan": [], "account": [], "positions_prev": []})
        self.assertIn("expects 'account' to be an object", str(context.exception))

    def test_validate_artifact_updates_rejects_undeclared_outputs(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_artifact_updates("reporter", {"metrics": {}})
        self.assertIn("artifact exporter", str(context.exception))

    def test_validate_artifact_updates_rejects_invalid_shape(self) -> None:
        with self.assertRaises(ValueError) as context:
            validate_artifact_updates("reporter", {"report_files": []})
        self.assertIn("expects 'report_files' to be an object", str(context.exception))

    def test_pipeline_catalog_describes_stage_contracts(self) -> None:
        service = TraderApiService(
            project_root=PROJECT_ROOT,
            output_root=PROJECT_ROOT / "outputs",
            default_config_path=PROJECT_ROOT / "app" / "config" / "pipeline.yaml",
            default_input_path=PROJECT_ROOT / "examples" / "input" / "daily_snapshot.json",
        )

        status, payload = service.get_pipeline_catalog()
        payload_dict = payload.to_dict()

        self.assertEqual(status, 200)
        self.assertIn("planning", payload_dict["presets"])
        self.assertEqual(payload_dict["stages"]["update_holding_actions"]["output_model"], "HoldingReviewStageOutput")
        self.assertEqual(payload_dict["stages"]["update_holding_actions"]["output_contract"]["holding_actions"], "HoldingActionRow[]")
        self.assertEqual(
            payload_dict["stages"]["update_holding_actions"]["input_snapshot_keys"],
            ["snapshot", "trade_date", "stage_notes", "snapshot_market", "market_data_context", "market_data_by_symbol"],
        )
        self.assertEqual(payload_dict["stages"]["selector"]["requires"], ["snapshot"])
        self.assertIn("tech_candidates", payload_dict["stages"]["selector"]["provides"])
        self.assertEqual(payload_dict["stages"]["selector"]["output_model"], "SelectorStageOutput")
        self.assertEqual(payload_dict["stages"]["selector"]["output_contract"]["tech_candidates"], "TechCandidateRow[]")
        self.assertEqual(payload_dict["stages"]["executor"]["output_model"], "ExecutorStageOutput")
        self.assertEqual(payload_dict["stages"]["executor"]["output_contract"]["nav"], "NavRow[]")
        self.assertIn("trade_plan", payload_dict["stages"]["executor"]["input_snapshot_keys"])
        self.assertEqual(payload_dict["stages"]["reporter"]["output_model"], "ReporterStageOutput")
        self.assertEqual(payload_dict["stages"]["reporter"]["output_contract"]["metrics"], "MetricsSummary")
        self.assertEqual(payload_dict["stages"]["reporter"]["artifact_outputs"], ["report_files"])
        self.assertIn("run_id", payload_dict["stages"]["reporter"]["input_snapshot_keys"])
        self.assertIn("stage_notes", payload_dict["runtime_managed_outputs"])
        self.assertEqual(payload_dict["artifact_managed_outputs"]["reporter"], ["report_files"])


class StageArtifactExportTests(unittest.TestCase):
    def test_export_stage_artifacts_writes_selector_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = RunContext(
                run_id="artifact-selector-demo",
                trade_date="2026-03-10",
                config={},
                input_path=root / "input.json",
                output_root=root,
                output_dir=root / "outputs" / "artifact-selector-demo",
            )
            ctx.ensure_output_dirs()

            stage_outputs = {
                "tech_candidates": [
                    {
                        "trade_date": "2026-03-10",
                        "symbol": "600519.SH",
                        "name": "贵州茅台",
                        "sector": "Consumer",
                        "board": "MAIN",
                        "last_price": 1642.0,
                        "prev_close": 1635.0,
                        "upper_limit": 1798.5,
                        "lower_limit": 1471.5,
                        "rule_pass": True,
                        "tech_score": 0.81,
                        "momentum_score": 0.82,
                        "breakout_score": 0.79,
                        "liquidity_score": 0.86,
                        "turnover_rate": 0.022,
                        "turnover_rate_proxy": 0.0,
                        "relative_volume": 1.1,
                        "relative_amount": 0.0,
                        "amount": 1100000000,
                        "daily_pct_change": 0.0043,
                        "return_5d": 0.0,
                        "return_20d": 0.0,
                        "ma20": 0.0,
                        "ma60": 0.0,
                        "price_vs_ma20": 0.0,
                        "price_vs_20d_high": 0.0,
                        "volatility_20d": 0.0,
                        "near_upper_limit": False,
                        "is_st": False,
                        "suspended": False,
                        "list_days": 8000,
                        "market_data_source": "snapshot",
                        "technical_flags": "",
                        "technical_summary": "",
                        "trigger_tags": "momentum|breakout",
                    }
                ]
            }

            result = export_stage_artifacts(ctx, "selector", stage_outputs)

            self.assertEqual(result, {})
            csv_path = ctx.artifact_path("tech_candidates_t.csv")
            self.assertTrue(csv_path.exists())
            self.assertIn("600519.SH", csv_path.read_text(encoding="utf-8"))

    def test_export_stage_artifacts_writes_reporter_outputs_and_updates_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = RunContext(
                run_id="artifact-reporter-demo",
                trade_date="2026-03-10",
                config={},
                input_path=root / "input.json",
                output_root=root,
                output_dir=root / "outputs" / "artifact-reporter-demo",
            )
            ctx.ensure_output_dirs()

            stage_outputs = {
                "metrics": {"trade_date": "2026-03-10", "filled_order_count": 1},
                "risk_report_markdown": "# Daily Report\n\nTest report\n",
            }

            result = export_stage_artifacts(ctx, "reporter", stage_outputs)

            self.assertIn("report_files", result)
            metrics_path = Path(result["report_files"]["metrics_t.json"])
            report_path = Path(result["report_files"]["risk_report_t.md"])
            self.assertTrue(metrics_path.exists())
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(metrics_path.read_text(encoding="utf-8"))["filled_order_count"], 1)
            self.assertIn("Test report", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
