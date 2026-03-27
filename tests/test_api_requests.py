from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.requests import NewsSearchQueryRequest, RunDailyJobRequest, StockScreenQueryRequest


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
                backend_dir=BACKEND_DIR,
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
                    backend_dir=BACKEND_DIR,
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


if __name__ == "__main__":
    unittest.main()
