from __future__ import annotations

import csv
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.server import build_server
from app.news_search import NewsSearchError


class ApiHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.output_root = self.root / "outputs"
        self.config_path = self.root / "pipeline.yaml"
        self.input_path = self.root / "daily_snapshot.json"

        self.config_path.write_text(
            "pipeline:\n"
            "  preset: full\n"
            "stock_screen:\n"
            "  default_page_size: 20\n"
            "news_search:\n"
            "  default_size: 8\n",
            encoding="utf-8",
        )
        self.input_path.write_text(
            json.dumps({"trade_date": "2026-03-10", "watchlist": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._seed_daily_output()

        self.server = build_server(
            host="127.0.0.1",
            port=0,
            project_root=PROJECT_ROOT,
            output_root=self.output_root,
            default_config_path=self.config_path,
            default_input_path=self.input_path,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown_server)

    def test_get_pipeline_catalog_exposes_stage_snapshot_contracts(self) -> None:
        status, payload = self._request("GET", "/pipeline/catalog")

        self.assertEqual(status, 200)
        self.assertIn("input_snapshot_keys", payload["stages"]["reporter"])
        self.assertIn("run_id", payload["stages"]["reporter"]["input_snapshot_keys"])
        self.assertIn("snapshot_market", payload["stages"]["selector"]["input_snapshot_keys"])

    def test_get_root_returns_unknown_path_when_frontend_is_removed(self) -> None:
        status, payload = self._request("GET", "/")

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "unknown path: /")

    def test_post_run_daily_rejects_invalid_json(self) -> None:
        status, payload = self._request(
            "POST",
            "/jobs/run-daily",
            body='{"broken"',
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 400)
        self.assertIn("invalid json", payload["error"])

    def test_post_run_daily_maps_missing_input_file_to_404(self) -> None:
        status, payload = self._request(
            "POST",
            "/jobs/run-daily",
            body={"input_file": str(self.root / "missing_snapshot.json")},
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 404)
        self.assertIn("file_not_found", payload["error"])

    def test_post_stock_screen_query_surfaces_request_validation_error(self) -> None:
        status, payload = self._request(
            "POST",
            "/stock-screen/query",
            body={},
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "keyword is required")

    def test_post_news_search_query_preserves_domain_error_status(self) -> None:
        with patch(
            "app.api.server.run_news_search_query",
            side_effect=NewsSearchError("news upstream unavailable", status_code=502),
        ):
            status, payload = self._request(
                "POST",
                "/news-search/query",
                body={"query": "立讯精密"},
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "news upstream unavailable")

    def test_get_position_detail_returns_position_with_related_rows(self) -> None:
        status, payload = self._request("GET", "/positions/detail?symbol=600519.SH")

        self.assertEqual(status, 200)
        self.assertEqual(payload["symbol"], "600519.SH")
        self.assertEqual(payload["position"]["quantity"], "300.0")
        self.assertEqual(payload["holding_action_count"], 1)
        self.assertEqual(payload["plan_count"], 1)
        self.assertEqual(payload["fill_count"], 1)
        self.assertEqual(payload["fills"][0]["status"], "FILLED")

    def test_post_operations_validate_reports_oversell(self) -> None:
        status, payload = self._request(
            "POST",
            "/operations/validate",
            body={
                "trade_date": "2026-03-10",
                "symbol": "600519.SH",
                "action": "SELL",
                "quantity": 300,
                "price": 1510,
            },
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["valid"])
        self.assertTrue(payload["position_found"])
        self.assertEqual(payload["normalized_action"], "EXIT")
        self.assertTrue(any("available_quantity" in item for item in payload["errors"]))

    def test_post_operations_submit_persists_entry_and_updates_follow_up_validation(self) -> None:
        status, payload = self._request(
            "POST",
            "/operations/submit",
            body={
                "trade_date": "2026-03-10",
                "symbol": "600519.SH",
                "action": "SELL",
                "quantity": 100,
                "price": 1510,
                "operator": "tester",
            },
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "submitted")
        ledger_path = Path(str(payload["ledger_path"]))
        self.assertTrue(ledger_path.exists())
        ledger_payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger_payload["entry_count"], 1)
        self.assertEqual(ledger_payload["entries"][0]["normalized_action"], "REDUCE")

        status, payload = self._request(
            "POST",
            "/operations/validate",
            body={
                "trade_date": "2026-03-10",
                "symbol": "600519.SH",
                "action": "SELL",
                "quantity": 150,
                "price": 1510,
            },
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["before_available_quantity"], 100.0)
        self.assertTrue(any("available=100" in item for item in payload["errors"]))

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        payload: bytes | None
        if isinstance(body, dict):
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = None

        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            connection.request(method, path, body=payload, headers=headers or {})
            response = connection.getresponse()
            status = response.status
            raw = response.read()
        finally:
            connection.close()

        text = raw.decode("utf-8") if raw else ""
        parsed = json.loads(text) if text else {}
        return status, parsed

    def _shutdown_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def _seed_daily_output(self) -> None:
        run_dir = self.output_root / "api-demo-20260310"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "final_payload.json").write_text(
            json.dumps(
                {
                    "run_id": "api-demo-20260310",
                    "snapshot": {"trade_date": "2026-03-10"},
                    "trade_date": "2026-03-10",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._write_csv(
            run_dir / "positions_t.csv",
            [
                {
                    "trade_date": "2026-03-10",
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "sector": "Consumer",
                    "board": "MAIN",
                    "quantity": 300.0,
                    "available_quantity": 200.0,
                    "avg_cost": 1480.0,
                    "prev_close": 1500.0,
                    "last_price": 1505.0,
                    "upper_limit": 1650.0,
                    "lower_limit": 1350.0,
                    "market_value": 451500.0,
                    "weight": 0.25,
                    "unrealized_pnl_pct": 0.0169,
                    "is_st": False,
                    "suspended": False,
                    "last_trade_date": "2026-03-09",
                }
            ],
        )
        self._write_csv(
            run_dir / "holding_actions_t.csv",
            [
                {
                    "symbol": "600519.SH",
                    "action_today": "HOLD",
                    "target_weight": 0.22,
                    "reason": "trend intact",
                }
            ],
        )
        self._write_csv(
            run_dir / "trade_plan_t.csv",
            [
                {
                    "symbol": "600519.SH",
                    "action": "REDUCE",
                    "status": "ACCEPTED",
                    "target_weight": 0.20,
                    "w_final": 0.20,
                }
            ],
        )
        self._write_csv(
            run_dir / "sim_fill_t.csv",
            [
                {
                    "trade_date": "2026-03-10",
                    "order_id": "20260310-600519SH-reduce-001",
                    "symbol": "600519.SH",
                    "name": "贵州茅台",
                    "board": "MAIN",
                    "action": "REDUCE",
                    "planned_price": 1510.0,
                    "fill_price": 1508.0,
                    "price_deviation_bps": -13.24,
                    "quantity": 100.0,
                    "filled_amount": 150800.0,
                    "commission": 45.24,
                    "stamp_duty": 75.40,
                    "transfer_fee": 1.51,
                    "total_fee": 122.15,
                    "status": "FILLED",
                    "note": "manual_seed",
                }
            ],
        )

    def _write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        fieldnames = list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
