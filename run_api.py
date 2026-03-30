from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI Trader HTTP API service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "outputs"))
    parser.add_argument("--default-config", default=str(PROJECT_ROOT / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--default-input", default=str(PROJECT_ROOT / "examples" / "input" / "daily_snapshot.json"))
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        project_root=PROJECT_ROOT,
        output_root=Path(args.output_root).resolve(),
        default_config_path=Path(args.default_config).resolve(),
        default_input_path=Path(args.default_input).resolve(),
    )
    print(f"AI Trader API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
