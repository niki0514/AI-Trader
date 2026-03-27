from __future__ import annotations

from pathlib import Path
import sys
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.responses import NewsSearchQueryResponse, PipelineCatalogResponse, StockScreenQueryResponse


class ApiResponseModelTests(unittest.TestCase):
    def test_stock_screen_response_omits_rows_when_not_requested(self) -> None:
        response = StockScreenQueryResponse.from_result(
            result={
                "request_id": "stock-screen-demo",
                "keyword": "今日涨幅2%的股票",
                "effective_keyword": "A股今日涨幅2%的股票",
                "market": "A股",
                "status": 0,
                "message": "ok",
                "business_code": "100",
                "business_msg": "ok",
                "result_type": 2000,
                "total": 2,
                "row_count": 2,
                "page_size": 50,
                "pages_fetched": 1,
                "fetch_all": True,
                "parser_text": "今日涨幅在[1.5%,2.5%]之间",
                "response_conditions": [{"describe": "cond"}],
                "total_condition": {"describe": "all"},
                "columns": [{"key": "SECURITY_CODE", "csv_header": "股票代码"}],
                "rows": [{"股票代码": "600519"}, {"股票代码": "300750"}],
                "artifacts": {"csv": "/tmp/stock.csv"},
            },
            preview_limit=1,
            include_rows=False,
        )
        payload = response.to_dict()

        self.assertEqual(payload["preview_count"], 1)
        self.assertEqual(payload["preview_rows"], [{"股票代码": "600519"}])
        self.assertNotIn("rows", payload)

    def test_news_search_response_omits_items_when_not_requested(self) -> None:
        response = NewsSearchQueryResponse.from_result(
            result={
                "request_id": "news-search-demo",
                "query": "立讯精密的资讯",
                "status": 0,
                "message": "ok",
                "business_status": 0,
                "business_code": 0,
                "business_message": "OK",
                "search_status": 0,
                "search_code": 0,
                "search_message": "OK",
                "protocol_type": "SEARCH_NEWS",
                "trace_id": "trace-001",
                "search_id": "search-id-001",
                "count": 1,
                "request": {"query": "立讯精密的资讯"},
                "extra_infos": {"decomposedQueries": None},
                "items": [
                    {
                        "index": 1,
                        "title": "立讯精密机构观点汇总",
                        "date": "2026-03-02 12:00:00",
                        "information_type": "REPORT",
                        "attach_type": "",
                        "jump_url": "https://report.example.com/1",
                        "trunk": "机构认为公司订单趋势良好。",
                    }
                ],
                "artifacts": {"result_json": "/tmp/news.json"},
            },
            preview_limit=1,
            excerpt_chars=8,
            include_items=False,
        )
        payload = response.to_dict()

        self.assertEqual(payload["preview_count"], 1)
        self.assertEqual(payload["preview_items"][0]["trunk_excerpt"], "机构认为公司订…")
        self.assertNotIn("items", payload)

    def test_pipeline_catalog_response_serializes_nested_stage_entries(self) -> None:
        response = PipelineCatalogResponse.from_payload(
            {
                "default_stage_order": ["selector", "analyst"],
                "presets": {"research": ["selector", "analyst"]},
                "prepared_payload_keys": ["trade_date"],
                "runtime_managed_outputs": ["stage_notes"],
                "artifact_managed_outputs": {"reporter": ["report_files"]},
                "stages": {
                    "selector": {
                        "requires": ["snapshot"],
                        "provides": ["tech_candidates"],
                        "artifact_outputs": [],
                        "output_model": "SelectorStageOutput",
                        "output_contract": {"tech_candidates": "TechCandidateRow[]"},
                        "input_snapshot_keys": ["snapshot", "trade_date"],
                        "description": "Build candidate rows.",
                    }
                },
            }
        )
        payload = response.to_dict()

        self.assertEqual(payload["default_stage_order"], ["selector", "analyst"])
        self.assertEqual(payload["stages"]["selector"]["output_model"], "SelectorStageOutput")
        self.assertEqual(payload["stages"]["selector"]["input_snapshot_keys"], ["snapshot", "trade_date"])


if __name__ == "__main__":
    unittest.main()
