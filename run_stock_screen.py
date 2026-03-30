from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_pipeline_config
from app.stock_screen import (
    StockScreenError,
    build_stock_screen_request_id,
    load_stock_screen_settings,
    run_stock_screen_query,
)
from app.utils import to_bool


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Eastmoney stock screen and export full CSV artifacts.")
    parser.add_argument("--keyword", required=True, help="Natural language stock screening keyword.")
    parser.add_argument("--market", default="", help="Optional market prefix: A股 / 港股 / 美股.")
    parser.add_argument("--page-no", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--fetch-all", default="true", help="Whether to auto-fetch all pages. true/false.")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "outputs" / "stock_screen"))
    parser.add_argument("--include-rows", action="store_true", help="Print all localized rows in the JSON summary.")
    args = parser.parse_args()

    config = load_pipeline_config(Path(args.config).resolve())
    settings = load_stock_screen_settings(config)
    request_id = args.request_id or build_stock_screen_request_id(args.keyword, args.market)

    try:
        result = run_stock_screen_query(
            keyword=args.keyword,
            settings=settings,
            market=args.market,
            page_no=max(args.page_no, 1),
            page_size=max(args.page_size, 1),
            fetch_all=to_bool(args.fetch_all, True),
            request_id=request_id,
            export_dir=Path(args.output_root).resolve() / request_id,
        )
    except StockScreenError as exc:
        print(json.dumps({"error": str(exc), "status_code": exc.status_code}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    payload = dict(result)
    rows = list(payload.get("rows", []))
    payload["preview_rows"] = rows[:10]
    payload["preview_count"] = min(len(rows), 10)
    if not args.include_rows:
        payload.pop("rows", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
