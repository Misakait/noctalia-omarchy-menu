from __future__ import annotations

import subprocess
import tomllib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PanelManifestContractTests(unittest.TestCase):
    def test_manifest_declares_the_api24_centered_menu_panel(self) -> None:
        manifest = tomllib.loads((PROJECT_ROOT / "plugin.toml").read_text(encoding="utf-8"))

        self.assertEqual(manifest["id"], "misakait/omarchy-menu")
        self.assertEqual(manifest["plugin_api"], 24)
        self.assertEqual(manifest["panel"], [{
            "id": "menu",
            "entry": "panel.luau",
            "width": 440,
            "height": 560,
            "placement": "floating",
            "position": "center",
            "open_near_click": False,
            "dismiss_on_outside_click": True,
            "keyboard_focus": "exclusive",
            "capture_keys": ["up", "down", "prior", "next", "left", "right"],
        }])

    def test_lua_mock_exercises_retained_panel_contract(self) -> None:
        result = subprocess.run(
            ["/usr/bin/lua", "tests/panel_harness.lua"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("panel harness: 13 passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
