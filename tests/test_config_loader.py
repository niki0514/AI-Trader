from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config.loader import load_pipeline_config


class ConfigLoaderTests(unittest.TestCase):
    def test_load_pipeline_config_requires_pyyaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "pipeline.yaml"
            config_path.write_text("pipeline:\n  preset: full\n", encoding="utf-8")

            with patch("app.config.loader.yaml", None), patch(
                "app.config.loader.YAML_IMPORT_ERROR",
                RuntimeError("missing dependency"),
            ):
                with self.assertRaises(RuntimeError) as context:
                    load_pipeline_config(config_path)

        self.assertIn("PyYAML is required", str(context.exception))

    def test_load_pipeline_config_merges_extends_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_path = root / "base.yaml"
            overlay_path = root / "overlay.yaml"
            base_path.write_text(
                "pipeline:\n"
                "  preset: full\n"
                "risk:\n"
                "  mode_caps:\n"
                "    neutral: 0.5\n"
                "selection:\n"
                "  source: stock_screen\n",
                encoding="utf-8",
            )
            overlay_path.write_text(
                "extends: base.yaml\n"
                "pipeline:\n"
                "  name: overlay-demo\n"
                "risk:\n"
                "  mode_caps:\n"
                "    risk_on: 0.7\n"
                "selection:\n"
                "  source: candidate_pool\n",
                encoding="utf-8",
            )

            config = load_pipeline_config(overlay_path)

        self.assertEqual(config["pipeline"]["preset"], "full")
        self.assertEqual(config["pipeline"]["name"], "overlay-demo")
        self.assertEqual(config["risk"]["mode_caps"]["neutral"], 0.5)
        self.assertEqual(config["risk"]["mode_caps"]["risk_on"], 0.7)
        self.assertEqual(config["selection"]["source"], "candidate_pool")


if __name__ == "__main__":
    unittest.main()
