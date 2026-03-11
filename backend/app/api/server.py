from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.adapters import read_csv, read_json, write_json
from app.config import load_pipeline_config
from app.pipeline import RunContext
from app.runner import run_pipeline

import re

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class DailyRunRef:
    trade_date: str
    run_id: str
    output_dir: Path
    updated_at: float
    source: str


class TraderApiService:
    def __init__(
        self,
        *,
        backend_dir: Path,
        output_root: Path,
        default_config_path: Path,
        default_input_path: Path,
        frontend_root: Path | None = None,
    ) -> None:
        self.backend_dir = backend_dir
        self.output_root = output_root
        self.default_config_path = default_config_path
        self.default_input_path = default_input_path
        self.frontend_root = frontend_root

    # -----------------------------
    # Jobs
    # -----------------------------
    def run_daily_job(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        input_path = Path(body.get("input_file") or self.default_input_path).resolve()
        config_path = Path(body.get("config_file") or self.default_config_path).resolve()
        output_root = Path(body.get("output_root") or self.output_root).resolve()

        snapshot = read_json(input_path)
        trade_date = str(body.get("trade_date") or snapshot.get("trade_date") or datetime.now().strftime("%Y-%m-%d"))
        if not _is_trade_date(trade_date):
            return 400, {"error": f"invalid trade_date: {trade_date}"}

        run_id = str(body.get("run_id") or _build_daily_run_id(trade_date))
        config = load_pipeline_config(config_path)
        output_dir = output_root / run_id

        ctx = RunContext(
            run_id=run_id,
            trade_date=trade_date,
            config=config,
            input_path=input_path,
            output_root=output_root,
            output_dir=output_dir,
            metadata={"config_path": str(config_path), "api_trigger": True},
        )
        initial_payload = {
            "run_id": run_id,
            "snapshot": snapshot,
            "input_file": str(input_path),
            "config_file": str(config_path),
        }
        result = run_pipeline(ctx, initial_payload)
        write_json(output_dir / "final_payload.json", result)

        metrics = dict(result.get("metrics", {}))
        report_files = dict(result.get("report_files", {}))
        return 200, {
            "job_id": run_id,
            "status": "completed",
            "mode": "sync",
            "run_id": run_id,
            "trade_date": trade_date,
            "output_dir": str(output_dir),
            "metrics": metrics,
            "artifacts": report_files,
        }

    # -----------------------------
    # Read endpoints
    # -----------------------------
    def get_positions_latest(self) -> tuple[int, dict[str, Any]]:
        refs = self._discover_daily_runs()
        latest = self._latest_ref(refs)
        if latest is None:
            return 404, {"error": "no daily outputs found"}

        rows = read_csv(latest.output_dir / "positions_t.csv")
        return 200, {
            "trade_date": latest.trade_date,
            "run_id": latest.run_id,
            "source": latest.source,
            "output_dir": str(latest.output_dir),
            "count": len(rows),
            "positions": rows,
        }

    def get_plans_by_date(self, trade_date: str) -> tuple[int, dict[str, Any]]:
        if not _is_trade_date(trade_date):
            return 400, {"error": f"invalid trade_date: {trade_date}"}

        ref = self._latest_ref_for_date(self._discover_daily_runs(), trade_date)
        if ref is None:
            return 404, {"error": f"no plan found for trade_date={trade_date}"}

        rows = read_csv(ref.output_dir / "trade_plan_t.csv")
        return 200, {
            "trade_date": trade_date,
            "run_id": ref.run_id,
            "source": ref.source,
            "output_dir": str(ref.output_dir),
            "count": len(rows),
            "plans": rows,
        }

    def get_fills_by_date(self, trade_date: str) -> tuple[int, dict[str, Any]]:
        if not _is_trade_date(trade_date):
            return 400, {"error": f"invalid trade_date: {trade_date}"}

        ref = self._latest_ref_for_date(self._discover_daily_runs(), trade_date)
        if ref is None:
            return 404, {"error": f"no fills found for trade_date={trade_date}"}

        rows = read_csv(ref.output_dir / "sim_fill_t.csv")
        return 200, {
            "trade_date": trade_date,
            "run_id": ref.run_id,
            "source": ref.source,
            "output_dir": str(ref.output_dir),
            "count": len(rows),
            "fills": rows,
        }

    def get_nav(self, start: str = "", end: str = "") -> tuple[int, dict[str, Any]]:
        if start and not _is_trade_date(start):
            return 400, {"error": f"invalid start: {start}"}
        if end and not _is_trade_date(end):
            return 400, {"error": f"invalid end: {end}"}
        if start and end and start > end:
            return 400, {"error": "start must be <= end"}

        latest_by_date: dict[str, DailyRunRef] = {}
        for ref in self._discover_daily_runs():
            current = latest_by_date.get(ref.trade_date)
            if current is None or ref.updated_at > current.updated_at:
                latest_by_date[ref.trade_date] = ref

        rows: list[dict[str, Any]] = []
        for trade_date in sorted(latest_by_date.keys()):
            if start and trade_date < start:
                continue
            if end and trade_date > end:
                continue

            ref = latest_by_date[trade_date]
            nav_rows = read_csv(ref.output_dir / "nav_t.csv")
            if not nav_rows:
                continue
            row = dict(nav_rows[-1])
            row["run_id"] = ref.run_id
            row["source"] = ref.source
            row["output_dir"] = str(ref.output_dir)
            rows.append(row)

        return 200, {
            "start": start,
            "end": end,
            "count": len(rows),
            "nav": rows,
        }

    def get_daily_report(self, trade_date: str) -> tuple[int, dict[str, Any]]:
        if not _is_trade_date(trade_date):
            return 400, {"error": f"invalid trade_date: {trade_date}"}

        ref = self._latest_ref_for_date(self._discover_daily_runs(), trade_date)
        if ref is None:
            return 404, {"error": f"no report found for trade_date={trade_date}"}

        metrics_path = ref.output_dir / "metrics_t.json"
        report_path = ref.output_dir / "risk_report_t.md"
        metrics = read_json(metrics_path) if metrics_path.exists() else {}
        report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

        return 200, {
            "trade_date": trade_date,
            "run_id": ref.run_id,
            "source": ref.source,
            "output_dir": str(ref.output_dir),
            "metrics": metrics,
            "risk_report_markdown": report_text,
        }

    def get_frontend_asset(self, request_path: str) -> tuple[Path, str] | None:
        if self.frontend_root is None or not self.frontend_root.exists():
            return None

        if request_path in {"", "/", "/index.html"}:
            asset_path = self.frontend_root / "index.html"
        elif request_path.startswith("/static/"):
            relative_path = request_path.removeprefix("/static/")
            static_root = self.frontend_root / "static"
            asset_path = (static_root / relative_path) if static_root.exists() else (self.frontend_root / relative_path)
        else:
            return None

        try:
            resolved_root = self.frontend_root.resolve()
            resolved_asset = asset_path.resolve()
        except FileNotFoundError:
            return None

        if resolved_root not in resolved_asset.parents and resolved_asset != resolved_root:
            return None
        if not resolved_asset.exists() or not resolved_asset.is_file():
            return None

        content_type = mimetypes.guess_type(str(resolved_asset))[0] or "application/octet-stream"
        return resolved_asset, content_type

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _discover_daily_runs(self) -> list[DailyRunRef]:
        refs: list[DailyRunRef] = []
        output_root = self.output_root
        if not output_root.exists():
            return refs

        # direct single-day runs: outputs/<run_id>/
        for run_dir in output_root.iterdir():
            if not run_dir.is_dir() or run_dir.name == "backtests":
                continue
            ref = self._build_ref_from_dir(run_dir, source="single_day")
            if ref is not None:
                refs.append(ref)

        # backtest day runs: outputs/backtests/<run_id>/days/<trade_date>/
        backtests_root = output_root / "backtests"
        if backtests_root.exists():
            for backtest_dir in backtests_root.iterdir():
                if not backtest_dir.is_dir():
                    continue
                days_dir = backtest_dir / "days"
                if not days_dir.exists():
                    continue
                for day_dir in days_dir.iterdir():
                    if not day_dir.is_dir():
                        continue
                    ref = self._build_ref_from_dir(day_dir, source=f"backtest:{backtest_dir.name}")
                    if ref is not None:
                        refs.append(ref)

        return refs

    def _build_ref_from_dir(self, output_dir: Path, source: str) -> DailyRunRef | None:
        payload_path = output_dir / "final_payload.json"
        if not payload_path.exists():
            return None

        try:
            payload = read_json(payload_path)
        except Exception:
            return None

        snapshot = dict(payload.get("snapshot", {}))
        trade_date = str(snapshot.get("trade_date") or payload.get("trade_date") or output_dir.name)
        if not _is_trade_date(trade_date):
            return None

        run_id = str(payload.get("run_id") or output_dir.name)
        updated_at = self._resolve_updated_at(output_dir)
        return DailyRunRef(
            trade_date=trade_date,
            run_id=run_id,
            output_dir=output_dir,
            updated_at=updated_at,
            source=source,
        )

    def _resolve_updated_at(self, output_dir: Path) -> float:
        candidates = [
            output_dir / "metrics_t.json",
            output_dir / "nav_t.csv",
            output_dir / "final_payload.json",
        ]
        existing = [path.stat().st_mtime for path in candidates if path.exists()]
        if existing:
            return max(existing)
        return output_dir.stat().st_mtime

    @staticmethod
    def _latest_ref(refs: list[DailyRunRef]) -> DailyRunRef | None:
        if not refs:
            return None
        return max(refs, key=lambda item: item.updated_at)

    @staticmethod
    def _latest_ref_for_date(refs: list[DailyRunRef], trade_date: str) -> DailyRunRef | None:
        candidates = [item for item in refs if item.trade_date == trade_date]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.updated_at)

def make_handler(service: TraderApiService) -> type[BaseHTTPRequestHandler]:
    class TraderApiHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/healthz":
                self._send_json(200, {"status": "ok"})
                return

            if path == "/positions/latest":
                status, payload = service.get_positions_latest()
                self._send_json(status, payload)
                return

            if path.startswith("/plans/"):
                trade_date = path.split("/", 2)[-1]
                status, payload = service.get_plans_by_date(trade_date)
                self._send_json(status, payload)
                return

            if path.startswith("/fills/"):
                trade_date = path.split("/", 2)[-1]
                status, payload = service.get_fills_by_date(trade_date)
                self._send_json(status, payload)
                return

            if path == "/nav":
                start = _first_query_value(query.get("start"), "")
                end = _first_query_value(query.get("end"), "")
                status, payload = service.get_nav(start=start, end=end)
                self._send_json(status, payload)
                return

            if path.startswith("/reports/daily/"):
                trade_date = path.split("/", 3)[-1]
                status, payload = service.get_daily_report(trade_date)
                self._send_json(status, payload)
                return

            asset = service.get_frontend_asset(path)
            if asset is not None:
                asset_path, content_type = asset
                self._send_file(200, asset_path.read_bytes(), content_type)
                return

            self._send_json(404, {"error": f"unknown path: {path}"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path != "/jobs/run-daily":
                self._send_json(404, {"error": f"unknown path: {path}"})
                return

            body = self._read_json_body()
            if body is None:
                return

            try:
                status, payload = service.run_daily_job(body)
                self._send_json(status, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"error": f"file_not_found: {exc}"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - fallback guard
                self._send_json(500, {"error": f"internal_error: {exc}"})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json_body(self) -> dict[str, Any] | None:
            content_length = self.headers.get("Content-Length", "0").strip()
            if not content_length:
                content_length = "0"
            try:
                length = int(content_length)
            except ValueError:
                self._send_json(400, {"error": "invalid Content-Length"})
                return None

            raw = self.rfile.read(length) if length > 0 else b"{}"
            if not raw:
                return {}
            try:
                loaded = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"invalid json: {exc}"})
                return None
            if not isinstance(loaded, dict):
                self._send_json(400, {"error": "json body must be an object"})
                return None
            return loaded

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_file(status_code, data, "application/json; charset=utf-8")

        def _send_file(self, status_code: int, data: bytes, content_type: str) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return TraderApiHandler


def build_server(
    *,
    host: str,
    port: int,
    backend_dir: Path,
    output_root: Path,
    default_config_path: Path,
    default_input_path: Path,
    frontend_root: Path | None = None,
) -> ThreadingHTTPServer:
    service = TraderApiService(
        backend_dir=backend_dir,
        output_root=output_root,
        default_config_path=default_config_path,
        default_input_path=default_input_path,
        frontend_root=frontend_root,
    )
    handler = make_handler(service)
    return ThreadingHTTPServer((host, port), handler)


def _first_query_value(values: list[str] | None, default: str) -> str:
    if not values:
        return default
    return str(values[0])


def _is_trade_date(value: str) -> bool:
    return bool(DATE_RE.fullmatch(value))


def _build_daily_run_id(trade_date: str) -> str:
    normalized = trade_date.replace("-", "")
    return f"single-day-{normalized}-{datetime.now().strftime('%H%M%S')}"
