from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import menu_adapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STOCK_MENU = Path("/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc")
COMPATIBILITY = PROJECT_ROOT / "compatibility.json"


class CompatibilityInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = menu_adapter.load_source(STOCK_MENU)
        self.document = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))

    def test_every_stock_action_and_provider_has_one_exact_classification(self) -> None:
        source = menu_adapter.load_source(STOCK_MENU)
        actionable = {
            menu_id: fields
            for menu_id, fields in source.items()
            if fields.get("action") or fields.get("provider")
        }
        self.assertTrue(COMPATIBILITY.exists(), "compatibility.json must be shipped")
        document = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))
        rules = document["rules"]

        self.assertEqual(len(actionable), 272)
        self.assertEqual(
            sum(bool(row.get("action")) for row in actionable.values()), 270
        )
        self.assertEqual(
            sum(bool(row.get("provider")) for row in actionable.values()), 2
        )
        self.assertEqual(set(rules), set(actionable))

        for menu_id, fields in actionable.items():
            with self.subTest(menu_id=menu_id):
                rule = rules[menu_id]
                self.assertEqual(
                    rule["match"],
                    {
                        "action": fields.get("action", ""),
                        "provider": fields.get("provider", ""),
                    },
                )
                self.assertIn(
                    rule["mode"], {"pass-through", "mapped", "provider", "disabled"}
                )

    def test_mapped_rule_resolves_nested_dispatch_for_exact_signature(self) -> None:
        entry = menu_adapter.normalize_menu(
            {"trigger.capture.screenshot": self.source["trigger.capture.screenshot"]}
        )["trigger.capture.screenshot"]

        resolved = menu_adapter.resolve_compatibility(
            entry,
            self.document["rules"],
            source="system",
        )

        self.assertEqual(resolved["compatibility_status"], "mapped")
        self.assertEqual(
            resolved["dispatch"],
            {"mode": "argv", "argv": ["niri", "msg", "action", "screenshot"]},
        )

    def test_disabled_inventory_matches_the_three_reviewed_reason_sets(self) -> None:
        expected = {
            "Hyprland only": {
                "system.screensaver",
                "trigger.capture.screenrecord.webcam",
                "trigger.hardware.laptop-display",
                "trigger.hardware.mirror-display",
                "trigger.hardware.touchpad",
                "trigger.hardware.touchscreen",
                "trigger.toggle.screensaver",
                "trigger.toggle.workspace-layout",
                "trigger.toggle.window-gaps",
                "trigger.toggle.one-window-ratio",
                "style.hyprland",
                "style.screensaver.text",
                "style.screensaver.image",
                "style.screensaver.default",
                "setup.config.hyprland",
                "setup.config.hyprsunset",
                "update.process.hyprsunset",
                "update.config.hyprland",
                "update.config.hyprsunset",
            },
            "Omarchy Shell only": {
                "learn.tmux-keybindings",
                "learn.herdr-keybindings",
                "trigger.emoji",
                "trigger.reminder.set",
                "trigger.tests.network-speedtest",
                "trigger.tests.disk-speedtest",
                "style.unlock",
                "setup.network.qr",
                "setup.plugin.enable",
                "setup.plugin.disable",
                "setup.plugin.add",
                "setup.plugin.clone",
                "setup.plugin.remove",
                "update.process.shell",
                "update.config.shell",
            },
            "Compatibility not reviewed": {
                "trigger.transcode",
                "install.style.theme",
                "install.windows",
                "install.preinstalls",
                "install.service.dropbox",
                "install.service.tailscale",
                "install.ai.dictation",
                "install.gaming.retro-launcher",
                "remove.theme",
                "remove.webapp",
                "remove.tui",
                "remove.windows",
                "remove.preinstalls",
                "remove.service.dropbox",
                "remove.service.tailscale",
                "remove.ai.dictation",
                "update.timezone",
            },
        }

        actual: dict[str, set[str]] = {}
        for menu_id, rule in self.document["rules"].items():
            if rule["mode"] == "disabled":
                actual.setdefault(rule["reason"], set()).add(menu_id)

        self.assertEqual(actual, expected)
        for reason, menu_ids in expected.items():
            for menu_id in menu_ids:
                with self.subTest(menu_id=menu_id):
                    self.assertTrue(self.document["rules"][menu_id]["force_visible"])

    def test_required_mapping_families_have_exact_dispatch_payloads(self) -> None:
        argv_mappings = {
            "apps": ["noctalia", "msg", "panel-open", "launcher"],
            "learn.keybindings": ["niri", "msg", "action", "show-hotkey-overlay"],
            "trigger.capture.screenshot": ["niri", "msg", "action", "screenshot"],
            "trigger.capture.color": ["niri", "msg", "pick-color"],
            "trigger.capture.screenrecord.no-audio": ["omarchy-capture-screenrecording"],
            "trigger.capture.screenrecord.desktop-audio": [
                "omarchy-capture-screenrecording",
                "--with-desktop-audio",
            ],
            "trigger.capture.screenrecord.microphone": [
                "omarchy-capture-screenrecording",
                "--with-desktop-audio",
                "--with-microphone-audio",
            ],
            "trigger.toggle.idle-lock": ["noctalia", "msg", "caffeine-toggle"],
            "trigger.toggle.notifications": [
                "noctalia",
                "msg",
                "notification-dnd-toggle",
            ],
            "trigger.toggle.nightlight": [
                "noctalia",
                "msg",
                "nightlight-force-toggle",
            ],
            "trigger.toggle.top-bar": ["noctalia", "msg", "bar-toggle"],
            "trigger.toggle.battery-percentage": [
                "noctalia",
                "msg",
                "settings-open",
                "bar",
            ],
            "style.theme": ["noctalia", "msg", "settings-open", "appearance"],
            "style.background": ["noctalia", "msg", "panel-toggle", "wallpaper"],
            "style.bar.transparency": ["noctalia", "msg", "settings-open", "bar"],
            "style.bar.position.top": ["noctalia", "msg", "settings-open", "bar"],
            "style.bar.position.bottom": ["noctalia", "msg", "settings-open", "bar"],
            "style.bar.position.left": ["noctalia", "msg", "settings-open", "bar"],
            "style.bar.position.right": ["noctalia", "msg", "settings-open", "bar"],
            "system.lock": ["noctalia", "msg", "session", "lock"],
            "system.logout": ["niri", "msg", "action", "quit", "--skip-confirmation"],
        }
        script_mappings = {
            "trigger.capture.text": "scripts/capture-text",
            "trigger.capture.qr": "scripts/capture-qr",
            "system.reboot": "scripts/system-reboot",
            "system.shutdown": "scripts/system-shutdown",
        }
        shell_mappings = {
            menu_id: 'omarchy-launch-config-editor "$HOME/.config/niri/config.kdl"'
            for menu_id in ("setup.monitors", "setup.keybindings", "setup.input")
        }

        mapped_ids = {
            menu_id
            for menu_id, rule in self.document["rules"].items()
            if rule["mode"] == "mapped"
        }
        self.assertEqual(
            mapped_ids,
            set(argv_mappings) | set(script_mappings) | set(shell_mappings),
        )
        for menu_id, argv in argv_mappings.items():
            with self.subTest(menu_id=menu_id):
                self.assertEqual(
                    self.document["rules"][menu_id]["dispatch"],
                    {"mode": "argv", "argv": argv}
                    | (
                        {"env": {"OMARCHY_SCREENRECORD_USE_PORTAL": "true"}}
                        if menu_id.startswith("trigger.capture.screenrecord.")
                        else {}
                    ),
                )
        for menu_id, script in script_mappings.items():
            with self.subTest(menu_id=menu_id):
                self.assertEqual(
                    self.document["rules"][menu_id]["dispatch"],
                    {"mode": "script", "script": script, "args": []},
                )
        for menu_id, command in shell_mappings.items():
            with self.subTest(menu_id=menu_id):
                rule = self.document["rules"][menu_id]
                self.assertEqual(
                    rule["dispatch"], {"mode": "shell", "command": command}
                )
                self.assertEqual(rule["when"], "")

    def test_missing_mapped_dependency_disables_without_exposing_dispatch(self) -> None:
        entry = menu_adapter.normalize_menu(
            {"capture": {"action": "stock-capture"}}
        )["capture"]
        rules = {
            "capture": {
                "match": {"action": "stock-capture", "provider": ""},
                "mode": "mapped",
                "dispatch": {
                    "mode": "argv",
                    "argv": ["niri", "msg", "action", "screenshot"],
                },
                "requires": ["niri", "grim"],
            }
        }

        try:
            resolved = menu_adapter.resolve_compatibility(
                entry,
                rules,
                source="system",
                dependency_available=lambda name: name != "niri",
            )
        except TypeError:
            resolved = {}

        self.assertEqual(resolved.get("compatibility_status"), "disabled")
        self.assertEqual(resolved.get("disabled_reason"), "Missing dependency: niri")
        self.assertTrue(resolved.get("force_visible"))
        self.assertNotIn("dispatch", resolved)

    def test_changed_or_missing_opaque_helper_digest_downgrades_exact_rule(self) -> None:
        with TemporaryDirectory() as directory:
            helper = Path(directory) / "omarchy-audited-helper"
            helper.write_bytes(b"audited helper\n")
            digest = hashlib.sha256(helper.read_bytes()).hexdigest()
            entry = menu_adapter.normalize_menu(
                {"audited": {"action": "omarchy-audited-helper"}}
            )["audited"]
            rules = {
                "audited": {
                    "match": {
                        "action": "omarchy-audited-helper",
                        "provider": "",
                    },
                    "mode": "pass-through",
                    "digests": {str(helper): digest},
                }
            }

            matched = menu_adapter.resolve_compatibility(
                entry, rules, source="system"
            )
            helper.write_bytes(b"changed helper\n")
            changed = menu_adapter.resolve_compatibility(
                entry, rules, source="system"
            )
            helper.unlink()
            missing = menu_adapter.resolve_compatibility(
                entry, rules, source="system"
            )

        self.assertEqual(matched["compatibility_status"], "pass-through")
        for result in (changed, missing):
            with self.subTest(result=result):
                self.assertEqual(result["compatibility_status"], "disabled")
                self.assertEqual(
                    result["disabled_reason"], "Compatibility not reviewed"
                )
                self.assertTrue(result["force_visible"])
                self.assertNotIn("dispatch", result)

    def test_opaque_runtime_helper_rules_pin_matching_dependency_digests(self) -> None:
        opaque_ids: set[str] = set()
        for menu_id, rule in self.document["rules"].items():
            runtime_text = ""
            if rule["mode"] == "pass-through":
                runtime_text = rule["match"]["action"]
            elif rule["mode"] == "mapped":
                dispatch = rule.get("dispatch", {})
                if dispatch.get("mode") == "argv":
                    runtime_text = " ".join(dispatch.get("argv", []))
                elif dispatch.get("mode") == "shell":
                    runtime_text = dispatch.get("command", "")
            elif menu_id == "style.font":
                runtime_text = "omarchy-font-list omarchy-font-current omarchy-font-set"
            if re.search(r"\bomarchy-[A-Za-z0-9_-]+\b", runtime_text):
                opaque_ids.add(menu_id)

        self.assertIn("about", opaque_ids)
        self.assertIn("trigger.capture.screenrecord.no-audio", opaque_ids)
        self.assertIn("style.font", opaque_ids)
        for menu_id in opaque_ids:
            with self.subTest(menu_id=menu_id):
                rule = self.document["rules"][menu_id]
                self.assertTrue(rule.get("digests"))
                self.assertEqual(menu_adapter.rule_digest_mismatches(rule), [])

        self.assertIn(
            "/usr/bin/omarchy-launch-about",
            self.document["rules"]["about"]["digests"],
        )
        self.assertIn(
            "/usr/bin/omarchy-font-set",
            self.document["rules"]["style.font"]["digests"],
        )
        self.assertNotIn(
            "/usr/bin/omarchy-restart-shell",
            self.document["rules"]["style.font"]["digests"],
        )

    def test_apps_provider_resolves_to_an_actionable_launcher_bridge(self) -> None:
        entry = menu_adapter.normalize_menu({"apps": self.source["apps"]})["apps"]

        resolved = menu_adapter.resolve_compatibility(
            entry,
            self.document["rules"],
            source="system",
            dependency_available=lambda _name: True,
        )

        self.assertEqual(resolved["kind"], "action")
        self.assertEqual(resolved["compatibility_status"], "mapped")
        self.assertEqual(
            resolved["dispatch"],
            {"mode": "argv", "argv": ["noctalia", "msg", "panel-open", "launcher"]},
        )

    def test_font_provider_builds_safe_argv_rows_with_value_sensitive_tokens(self) -> None:
        entries = menu_adapter.normalize_menu({"style.font": self.source["style.font"]})
        entries["style.font"] = menu_adapter.resolve_compatibility(
            entries["style.font"],
            self.document["rules"],
            source="system",
            dependency_available=lambda _name: True,
        )

        outputs = {
            ("omarchy-font-list",): "Fira Code\nJetBrains Mono\n",
            ("omarchy-font-current",): "Fira Code\n",
        }
        first = menu_adapter.expand_providers(
            entries, lambda argv: outputs[tuple(argv)]
        )

        font_rows = [
            row
            for row in first.values()
            if isinstance(row, dict) and row.get("parent") == "style.font"
        ]
        self.assertEqual(
            [row["label"] for row in font_rows], ["Fira Code", "JetBrains Mono"]
        )
        self.assertTrue(font_rows[0]["provider_checked"])
        self.assertEqual(
            font_rows[1]["dispatch"],
            {
                "mode": "script",
                "script": "scripts/font-set",
                "args": ["JetBrains Mono"],
            },
        )

        changed_outputs = outputs | {
            ("omarchy-font-list",): "Fira Code\nJetBrains Mono NL\n"
        }
        second = menu_adapter.expand_providers(
            entries, lambda argv: changed_outputs[tuple(argv)]
        )
        changed_row = next(
            row
            for row in second.values()
            if isinstance(row, dict) and row.get("label") == "JetBrains Mono NL"
        )
        self.assertNotEqual(
            menu_adapter.action_token(font_rows[1]),
            menu_adapter.action_token(changed_row),
        )

    def test_read_only_audit_fails_for_unclassified_or_changed_stock_rows(self) -> None:
        report = menu_adapter.audit_inventory(self.source, self.document)

        self.assertTrue(report.get("ok"))
        self.assertEqual(report.get("stockRows"), 272)
        self.assertEqual(
            report.get("counts"),
            {"pass-through": 192, "mapped": 28, "provider": 1, "disabled": 51},
        )
        self.assertEqual(report.get("missing"), [])
        self.assertEqual(report.get("signatureMismatches"), [])
        self.assertEqual(report.get("digestMismatches"), [])

        missing_document = json.loads(json.dumps(self.document))
        del missing_document["rules"]["about"]
        missing = menu_adapter.audit_inventory(self.source, missing_document)
        changed_source = json.loads(json.dumps(self.source))
        changed_source["about"]["action"] = "omarchy-launch-about-v2"
        changed = menu_adapter.audit_inventory(changed_source, self.document)

        self.assertFalse(missing["ok"])
        self.assertEqual(missing["missing"], ["about"])
        self.assertFalse(changed["ok"])
        self.assertEqual(changed["signatureMismatches"], ["about"])

    def test_audit_command_reports_json_and_nonzero_for_unclassified_source(self) -> None:
        command = PROJECT_ROOT / "tools/audit_compatibility.py"
        self.assertTrue(command.is_file(), "read-only audit command must be shipped")

        good = subprocess.run(
            [str(command)], text=True, capture_output=True, timeout=5, check=False
        )
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertTrue(json.loads(good.stdout)["ok"])

        with TemporaryDirectory() as directory:
            source = Path(directory) / "menu.jsonc"
            source.write_text(
                '{"future": {"action": "omarchy-future-helper"}}',
                encoding="utf-8",
            )
            bad = subprocess.run(
                [str(command), "--source", str(source)],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )

        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)["missing"], ["future"])


if __name__ == "__main__":
    unittest.main()
