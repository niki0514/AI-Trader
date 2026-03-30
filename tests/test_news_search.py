from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.news_search import NewsSearchError, NewsSearchSettings, run_news_search_query


def _mock_payload(*, query: str) -> dict[str, object]:
    return {
        "status": 0,
        "message": "ok",
        "data": {
            "requestId": None,
            "message": "OK",
            "status": 0,
            "code": 0,
            "data": {
                "protocolType": "SEARCH_NEWS",
                "id": "search-id-001",
                "refSeq": None,
                "llmSearchRequest": {
                    "query": query,
                    "size": 2,
                    "traceId": "trace-001",
                },
                "llmSearchResponse": {
                    "status": 0,
                    "code": 0,
                    "message": "OK",
                    "traceId": "trace-001",
                    "extraInfos": {"decomposedQueries": None},
                    "data": [
                        {
                            "code": "AN202603021820191371",
                            "title": "立讯精密:关于股份回购进展情况的公告",
                            "content": "立讯精密工业股份有限公司关于股份回购进展情况的公告。",
                            "date": "2026-03-03 00:18:13",
                            "informationType": "NOTICE",
                            "jumpUrl": "https://pdf.example.com/notice.pdf",
                            "rankScore": 0.0,
                            "indexAttention": True,
                            "attachType": "PDF",
                            "recallIndex": "an_intention-0",
                            "showText": "<div>立讯精密工业股份有限公司关于股份回购进展情况的公告。</div>",
                        },
                        {
                            "code": "RW202603020000000001",
                            "title": "立讯精密机构观点汇总",
                            "content": "",
                            "date": "2026-03-02 12:00:00",
                            "informationType": "REPORT",
                            "jumpUrl": "https://report.example.com/1",
                            "rankScore": 9.9,
                            "indexAttention": False,
                            "attachType": "",
                            "recallIndex": "report-0",
                            "showText": "<p>机构认为公司订单趋势良好。</p>",
                        },
                    ],
                },
            },
            "stack": None,
        },
    }


class NewsSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = NewsSearchSettings(
            endpoint="https://example.com/news-search",
            api_key_env="MX_APIKEY",
            timeout_seconds=3,
            default_size=2,
        )

    def test_run_news_search_query_exports_markdown_and_json(self) -> None:
        requests: list[dict[str, object]] = []

        def fake_request_search(payload: dict[str, object], settings: NewsSearchSettings, api_key: str) -> dict[str, object]:
            del settings
            self.assertEqual(api_key, "demo-key")
            requests.append(payload)
            return _mock_payload(query=str(payload["query"]))

        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "news-search-demo"
            with patch.dict(os.environ, {"MX_APIKEY": "demo-key"}, clear=False):
                result = run_news_search_query(
                    query="立讯精密的资讯",
                    settings=self.settings,
                    export_dir=export_dir,
                    request_search=fake_request_search,
                    request_id="news-search-demo",
                )

            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["query"], "立讯精密的资讯")
            self.assertEqual(result["count"], 2)
            self.assertEqual(result["protocol_type"], "SEARCH_NEWS")
            self.assertEqual(result["items"][0]["title"], "立讯精密:关于股份回购进展情况的公告")
            self.assertEqual(result["items"][1]["trunk"], "机构认为公司订单趋势良好。")

            summary_path = Path(result["artifacts"]["result_json"])
            markdown_path = Path(result["artifacts"]["result_markdown"])
            raw_path = Path(result["artifacts"]["raw_json"])

            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(raw_path.exists())

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["request_id"], "news-search-demo")
            self.assertEqual(summary["count"], 2)

            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# 东方财富资讯搜索结果", markdown)
            self.assertIn("立讯精密机构观点汇总", markdown)
            self.assertIn("机构认为公司订单趋势良好。", markdown)

    def test_run_news_search_query_requires_apikey_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(NewsSearchError) as context:
                run_news_search_query(
                    query="立讯精密的资讯",
                    settings=self.settings,
                    request_search=lambda payload, settings, api_key: _mock_payload(query="立讯精密的资讯"),
                )
        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("missing env MX_APIKEY", str(context.exception))


if __name__ == "__main__":
    unittest.main()
