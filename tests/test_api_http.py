from __future__ import annotations

import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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

        self.server = build_server(
            host="127.0.0.1",
            port=0,
            backend_dir=BACKEND_DIR,
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


if __name__ == "__main__":
    unittest.main()
