from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI Trader backend HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--output-root", default=str(BACKEND_DIR / "outputs"))
    parser.add_argument("--default-config", default=str(BACKEND_DIR / "app" / "config" / "pipeline.yaml"))
    parser.add_argument("--default-input", default=str(BACKEND_DIR / "examples" / "input" / "daily_snapshot.json"))
    parser.add_argument("--frontend-dir", default=str(BACKEND_DIR.parent / "frontend" / "dist"))
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        backend_dir=BACKEND_DIR,
        output_root=Path(args.output_root).resolve(),
        default_config_path=Path(args.default_config).resolve(),
        default_input_path=Path(args.default_input).resolve(),
        frontend_root=Path(args.frontend_dir).resolve(),
    )
    print(f"AI Trader API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
