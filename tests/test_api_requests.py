from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.requests import NewsSearchQueryRequest, OperationEntryRequest, RunDailyJobRequest, StockScreenQueryRequest


class RunDailyJobRequestTests(unittest.TestCase):
    def test_from_body_uses_inline_snapshot_and_canonical_pipeline_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = RunDailyJobRequest.from_body(
                {
                    "run_id": "demo-run",
                    "trade_date": "2026-03-11",
                    "pipeline_preset": "planning",
                    "pipeline_stages": ["selector", "analyst"],
                    "snapshot": {"watchlist": []},
                },
                project_root=PROJECT_ROOT,
                default_config_path=root / "pipeline.yaml",
                default_input_path=root / "input.json",
                default_output_root=root / "outputs",
            )

        self.assertEqual(request.run_id, "demo-run")
        self.assertEqual(request.trade_date, "2026-03-11")
        self.assertEqual(request.pipeline_preset, "planning")
        self.assertEqual(request.pipeline_stages, ["selector", "analyst"])
        self.assertEqual(request.snapshot_input.input_label, "<inline_snapshot>")

    def test_from_body_rejects_non_array_pipeline_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ValueError) as context:
                RunDailyJobRequest.from_body(
                    {
                        "snapshot": {"watchlist": []},
                        "pipeline_stages": "selector,analyst",
                    },
                    project_root=PROJECT_ROOT,
                    default_config_path=root / "pipeline.yaml",
                    default_input_path=root / "input.json",
                    default_output_root=root / "outputs",
                )

        self.assertIn("pipeline_stages", str(context.exception))


class StockScreenQueryRequestTests(unittest.TestCase):
    def test_from_body_uses_canonical_page_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = StockScreenQueryRequest.from_body(
                {
                    "keyword": "今日涨幅2%的股票",
                    "market": "A股",
                    "page_no": 2,
                    "page_size": 50,
                    "fetch_all": True,
                },
                default_config_path=root / "pipeline.yaml",
                default_output_root=root / "outputs",
            )

        self.assertEqual(request.keyword, "今日涨幅2%的股票")
        self.assertEqual(request.page_no, 2)
        self.assertEqual(request.page_size, 50)
        self.assertTrue(request.fetch_all)

    def test_from_body_rejects_invalid_page_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ValueError) as context:
                StockScreenQueryRequest.from_body(
                    {
                        "keyword": "今日涨幅2%的股票",
                        "page_no": 0,
                    },
                    default_config_path=root / "pipeline.yaml",
                    default_output_root=root / "outputs",
                )

        self.assertIn("page_no", str(context.exception))


class NewsSearchQueryRequestTests(unittest.TestCase):
    def test_from_body_uses_canonical_news_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = NewsSearchQueryRequest.from_body(
                {
                    "query": "立讯精密的资讯",
                    "size": 12,
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-16",
                    "child_search_type": "announcement",
                },
                default_config_path=root / "pipeline.yaml",
                default_output_root=root / "outputs",
            )

        self.assertEqual(request.query, "立讯精密的资讯")
        self.assertEqual(request.size, 12)
        self.assertEqual(request.start_date, "2026-03-01")
        self.assertEqual(request.end_date, "2026-03-16")
        self.assertEqual(request.child_search_type, "announcement")


class OperationEntryRequestTests(unittest.TestCase):
    def test_from_body_parses_manual_operation_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = OperationEntryRequest.from_body(
                {
                    "trade_date": "2026-03-11",
                    "symbol": "600519.sh",
                    "action": "sell",
                    "quantity": "100",
                    "price": "1510.5",
                    "operator": "alice",
                    "note": "manual trade",
                },
                default_config_path=root / "pipeline.yaml",
                default_output_root=root / "outputs",
            )

        self.assertEqual(request.trade_date, "2026-03-11")
        self.assertEqual(request.symbol, "600519.sh")
        self.assertEqual(request.action, "sell")
        self.assertEqual(request.quantity, 100.0)
        self.assertEqual(request.price, 1510.5)
        self.assertEqual(request.operator, "alice")
        self.assertEqual(request.note, "manual trade")
        self.assertEqual(request.source, "manual_entry")

    def test_from_body_rejects_invalid_quantity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ValueError) as context:
                OperationEntryRequest.from_body(
                    {
                        "trade_date": "2026-03-11",
                        "symbol": "600519.SH",
                        "action": "SELL",
                        "quantity": 0,
                        "price": 1510,
                    },
                    default_config_path=root / "pipeline.yaml",
                    default_output_root=root / "outputs",
                )

        self.assertIn("quantity", str(context.exception))


if __name__ == "__main__":
    unittest.main()
