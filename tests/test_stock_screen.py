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

from app.stock_screen import StockScreenError, StockScreenSettings, run_stock_screen_query


def _mock_payload(*, rows: list[dict[str, object]], total: int) -> dict[str, object]:
    return {
        "status": 0,
        "message": "ok",
        "data": {
            "code": "100",
            "msg": "ok",
            "data": {
                "resultType": 2000,
                "parserText": "今日涨幅在[1.5%,2.5%]之间",
                "responseConditionList": [
                    {"describe": "今日涨幅在[1.5%,2.5%]之间", "stockCount": total}
                ],
                "totalCondition": {
                    "describe": "今日涨幅在[1.5%,2.5%]之间",
                    "stockCount": total,
                },
                "result": {
                    "total": total,
                    "totalRecordCount": total,
                    "columns": [
                        {"key": "SECURITY_CODE", "title": "股票代码", "dataType": "String"},
                        {"key": "SECURITY_SHORT_NAME", "title": "股票简称", "dataType": "String"},
                        {"key": "CHG", "title": "涨跌幅 (%)", "unit": "%", "dataType": "Double"},
                    ],
                    "dataList": rows,
                },
            },
        },
    }


class StockScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = StockScreenSettings(
            endpoint="https://example.com/stock-screen",
            api_key_env="MX_APIKEY",
            timeout_seconds=3,
            default_page_size=2,
            fetch_all_pages=True,
            max_pages=10,
        )

    def test_run_stock_screen_query_fetches_all_pages_and_exports_artifacts(self) -> None:
        requests: list[dict[str, object]] = []

        def fake_request_page(payload: dict[str, object], settings: StockScreenSettings, api_key: str) -> dict[str, object]:
            del settings
            self.assertEqual(api_key, "demo-key")
            requests.append(payload)
            page_no = int(payload["pageNo"])
            if page_no == 1:
                return _mock_payload(
                    rows=[
                        {"SECURITY_CODE": "600519", "SECURITY_SHORT_NAME": "贵州茅台", "CHG": 2.01},
                        {"SECURITY_CODE": "300750", "SECURITY_SHORT_NAME": "宁德时代", "CHG": 1.92},
                    ],
                    total=3,
                )
            return _mock_payload(
                rows=[
                    {"SECURITY_CODE": "601899", "SECURITY_SHORT_NAME": "紫金矿业", "CHG": 1.88}
                ],
                total=3,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "stock-screen-demo"
            with patch.dict(os.environ, {"MX_APIKEY": "demo-key"}, clear=False):
                result = run_stock_screen_query(
                    keyword="今日涨幅2%的股票",
                    market="A股",
                    settings=self.settings,
                    page_size=2,
                    export_dir=export_dir,
                    request_page=fake_request_page,
                    request_id="stock-screen-demo",
                )

            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0]["keyword"], "A股今日涨幅2%的股票")
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["row_count"], 3)
            self.assertEqual(result["pages_fetched"], 2)
            self.assertEqual(result["columns"][0]["csv_header"], "股票代码")
            self.assertEqual(result["rows"][0]["股票简称"], "贵州茅台")

            csv_path = Path(result["artifacts"]["csv"])
            description_path = Path(result["artifacts"]["description_json"])
            raw_path = Path(result["artifacts"]["raw_json"])

            self.assertTrue(csv_path.exists())
            self.assertTrue(description_path.exists())
            self.assertTrue(raw_path.exists())

            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("股票代码,股票简称,涨跌幅 (%)", csv_text)
            self.assertIn("600519,贵州茅台,2.01", csv_text)

            description = json.loads(description_path.read_text(encoding="utf-8"))
            self.assertEqual(description["request_id"], "stock-screen-demo")
            self.assertEqual(description["total"], 3)
            self.assertEqual(description["columns"][0]["key"], "SECURITY_CODE")

    def test_run_stock_screen_query_requires_apikey_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(StockScreenError) as context:
                run_stock_screen_query(
                    keyword="今日涨幅2%的股票",
                    settings=self.settings,
                    request_page=lambda payload, settings, api_key: _mock_payload(rows=[], total=0),
                )
        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("missing env MX_APIKEY", str(context.exception))


if __name__ == "__main__":
    unittest.main()
