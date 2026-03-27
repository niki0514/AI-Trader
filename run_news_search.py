from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_pipeline_config
from app.news_search import (
    NewsSearchError,
    build_news_search_request_id,
    load_news_search_settings,
    run_news_search_query,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Eastmoney news search and export readable markdown artifacts.")
    parser.add_argument("--query", required=True, help="Natural language financial news query.")
    parser.add_argument("--size", type=int, default=12, help="Maximum number of results to request.")
    parser.add_argument("--start-date", default="", help="Optional start date passed to the upstream API.")
    parser.add_argument("--end-date", default="", help="Optional end date passed to the upstream API.")
    parser.add_argument("--child-search-type", default="", help="Optional upstream childSearchType.")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--config", default=str(BACKEND_DIR / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--output-root", default=str(BACKEND_DIR / "outputs" / "news_search"))
    parser.add_argument("--include-items", action="store_true", help="Print all normalized items in the JSON summary.")
    args = parser.parse_args()

    config = load_pipeline_config(Path(args.config).resolve())
    settings = load_news_search_settings(config)
    request_id = args.request_id or build_news_search_request_id(args.query)

    try:
        result = run_news_search_query(
            query=args.query,
            settings=settings,
            size=max(args.size, 1),
            start_date=args.start_date,
            end_date=args.end_date,
            child_search_type=args.child_search_type,
            request_id=request_id,
            export_dir=Path(args.output_root).resolve() / request_id,
        )
    except NewsSearchError as exc:
        print(json.dumps({"error": str(exc), "status_code": exc.status_code}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    payload = dict(result)
    items = list(payload.get("items", []))
    payload["preview_items"] = [
        {
            "index": item.get("index"),
            "title": item.get("title"),
            "date": item.get("date"),
            "information_type": item.get("information_type"),
            "trunk_excerpt": item.get("trunk_excerpt"),
        }
        for item in items[:5]
    ]
    payload["preview_count"] = min(len(items), 5)
    if not args.include_items:
        payload.pop("items", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
