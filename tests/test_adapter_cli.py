from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import menu_adapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT_ROOT / "menu_adapter.py"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _compat(rule_id: str, action: str, dispatch: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "omarchyPackage": "test-package",
        "rules": {
            rule_id: {
                "match": {"action": action, "provider": ""},
                "mode": "mapped",
                "dispatch": dispatch,
            }
        },
    }


class StrictLoadingTests(unittest.TestCase):
    def test_jsonc_duplicate_keys_unterminated_comments_and_reserved_ids_fail(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "menu.jsonc"
            bad_documents = (
                '{"one": {"action": "a"}, "one": {"action": "b"}}',
                '{"one": {"action": "a"}} /* unfinished',
                '{"": {"action": "a"}}',
                '{"root": {"action": "a"}}',
            )
            for document in bad_documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaises(menu_adapter.SourceError):
                        menu_adapter.load_source(path)

    def test_wrong_action_provider_and_guard_types_fail_whole_source(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "menu.jsonc"
            for field in ("action", "provider", "when", "checked", "disabled"):
                with self.subTest(field=field):
                    _write(path, {"one": {field: ["not", "a", "string"]}})
                    with self.assertRaises(menu_adapter.SourceError):
                        menu_adapter.load_source(path)

    def test_invalid_utf8_is_a_source_error(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "menu.jsonc"
            path.write_bytes(b'{"one": {"label": "\xff"}}')
            with self.assertRaises(menu_adapter.SourceError):
                menu_adapter.load_source(path)

    def test_compatibility_schema_and_security_fields_are_strict(self) -> None:
        valid = _compat("one", "safe", {"mode": "argv", "argv": ["true"]})
        malformed = [
            {},
            {"schemaVersion": 2, "rules": {}},
            {"schemaVersion": 1, "rules": []},
            {**valid, "rules": {"one": {"mode": "mapped"}}},
            _compat("one", "safe", {"mode": "argv", "argv": []}),
            _compat("one", "safe", {"mode": "argv", "argv": ["true", "a\0b"]}),
            _compat("one", "safe", {"mode": "script", "script": "/tmp/x", "args": []}),
            _compat("one", "safe", {"mode": "shell", "command": 7}),
        ]
        malformed.append(
            {
                "schemaVersion": 1,
                "rules": {
                    "one": {
                        "match": {"action": "safe", "provider": ""},
                        "mode": "mapped",
                        "dispatch": {
                            "mode": "argv",
                            "argv": ["true"],
                            "env": {"BAD": "x\0y"},
                        },
                    }
                },
            }
        )
        with_unknown_security_field = _compat(
            "one", "safe", {"mode": "argv", "argv": ["true"]}
        )
        with_unknown_security_field["rules"]["one"]["env"] = {"BAD": 7}
        malformed.append(with_unknown_security_field)
        bad_env_name = _compat(
            "one", "safe", {"mode": "argv", "argv": ["true"], "env": {"A=B": "x"}}
        )
        malformed.append(bad_env_name)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "compatibility.json"
            for document in malformed:
                with self.subTest(document=document):
                    _write(path, document)
                    with self.assertRaises(menu_adapter.SourceError):
                        menu_adapter.load_compatibility(path)


class ModelBuilderTests(unittest.TestCase):
    def _paths(self, directory: Path) -> tuple[Path, Path, Path]:
        system = directory / "system.jsonc"
        extension = directory / "extension.jsonc"
        compatibility = directory / "compatibility.json"
        return system, extension, compatibility

    def test_label_only_override_keeps_stock_rule_but_action_change_is_extension_owned(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            system, extension, compatibility = self._paths(root)
            _write(system, {"one": {"label": "Stock", "action": "stock-action"}})
            _write(compatibility, _compat("one", "stock-action", {"mode": "argv", "argv": ["true"]}))
            _write(extension, {"one": {"label": "Renamed"}})
            retained = menu_adapter.build_model(
                system, extension, compatibility,
                guard_runner=lambda _value: True,
                provider_runner=lambda _argv: "",
                dependency_available=lambda _name: True,
            )
            _write(extension, {"one": {"action": "printf extension"}})
            changed = menu_adapter.build_model(
                system, extension, compatibility,
                guard_runner=lambda _value: True,
                provider_runner=lambda _argv: "",
                dependency_available=lambda _name: True,
            )

        self.assertEqual(retained["entries"]["one"]["compatibility_status"], "mapped")
        self.assertEqual(changed["entries"]["one"]["compatibility_status"], "user-pass-through")

    def test_revision_is_stable_across_guard_results_and_changes_with_extension(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            system, extension, compatibility = self._paths(root)
            _write(system, {"one": {"action": "safe", "when": "volatile"}})
            _write(extension, {})
            _write(compatibility, _compat("one", "safe", {"mode": "argv", "argv": ["true"]}))
            visible = menu_adapter.build_model(system, extension, compatibility, guard_runner=lambda _x: True, provider_runner=lambda _x: "", dependency_available=lambda _x: True)
            hidden = menu_adapter.build_model(system, extension, compatibility, guard_runner=lambda _x: False, provider_runner=lambda _x: "", dependency_available=lambda _x: True)
            _write(extension, {"one": {"label": "changed"}})
            changed = menu_adapter.build_model(system, extension, compatibility, guard_runner=lambda _x: True, provider_runner=lambda _x: "", dependency_available=lambda _x: True)

        self.assertEqual(visible["revision"], hidden["revision"])
        self.assertNotEqual(visible["revision"], changed["revision"])

    def test_view_schema_is_exact_redacted_and_tokens_only_enabled_visible_actions(self) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "ok": {"action": "SECRET_ACTION", "provider": "safe-provider"},
                "hidden": {"action": "SECRET_HIDDEN"},
                "disabled": {"action": "SECRET_DISABLED"},
            }
        )
        for menu_id, entry in entries.items():
            entry.update(
                visible=menu_id != "hidden",
                enabled=menu_id not in {"hidden", "disabled"},
                checked_state=False,
                disabled_state=menu_id == "disabled",
                dispatch={"mode": "argv", "argv": ["SECRET_ARG"]},
                effective_guards={"when": "SECRET_GUARD"},
            )
        tree = menu_adapter.finalize_tree(entries)
        view = menu_adapter.build_view_model(
            tree,
            "revision",
            source={"omarchyPackage": "pkg", "extensionLoaded": True},
        )
        entry_keys = {
            "id", "parent", "kind", "icon", "iconFont", "label", "title",
            "target", "description", "aliases", "provider", "header", "children",
            "visible", "enabled", "checked", "disabled", "compatibilityStatus",
            "disabledReason", "order", "breadcrumb", "searchText",
        }

        self.assertEqual(set(view), {"schemaVersion", "revision", "root", "entries", "warnings", "source"})
        self.assertEqual(set(view["entries"]["root"]), entry_keys)
        self.assertEqual(set(view["entries"]["ok"]), entry_keys | {"actionToken"})
        self.assertNotIn("actionToken", view["entries"]["hidden"])
        self.assertNotIn("actionToken", view["entries"]["disabled"])
        serialized = json.dumps(view)
        for secret in ("SECRET_ACTION", "SECRET_HIDDEN", "SECRET_DISABLED", "SECRET_ARG", "SECRET_GUARD"):
            self.assertNotIn(secret, serialized)


class ProcessBoundaryTests(unittest.TestCase):
    def test_guard_timeout_kills_and_reaps_descendant_process_group(self) -> None:
        with TemporaryDirectory() as directory:
            child_pid = Path(directory) / "child.pid"
            runner = menu_adapter.GuardRunner(timeout=0.3)
            expression = f"sleep 5 & echo $! > {child_pid}; wait"
            self.assertFalse(runner(expression))
            deadline = time.monotonic() + 1
            while not child_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(child_pid.exists())
            pid = int(child_pid.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_guard_queue_timeout_starts_when_worker_starts(self) -> None:
        entries = {
            str(index): {
                "id": str(index),
                "kind": "action",
                "effective_guards": {"when": str(index), "checked": "", "disabled": ""},
            }
            for index in range(9)
        }
        evaluated, _warnings = menu_adapter.evaluate_guards(
            entries,
            lambda _expression: (time.sleep(0.04) or True),
            per_guard_timeout=0.06,
            overall_timeout=1,
            max_workers=8,
        )
        self.assertTrue(all(entry["visible"] for entry in evaluated.values()))

    def test_provider_limits_are_atomic_and_warnings_do_not_leak_output(self) -> None:
        entries = {
            "fonts": {
                "id": "fonts", "kind": "menu", "provider": "fonts", "order": 0,
                "compatibility_status": "provider", "compatibility_disabled": False,
            }
        }
        warnings: list[str] = []
        expanded = menu_adapter.expand_providers(
            entries,
            lambda argv: "Good\n" if argv[-1].endswith("list") else (_ for _ in ()).throw(menu_adapter.ProviderError("PRIVATE_OUTPUT")),
            warnings=warnings,
        )
        self.assertEqual(set(expanded), {"fonts"})
        self.assertEqual(warnings, ["Provider unavailable: fonts"])
        self.assertNotIn("PRIVATE_OUTPUT", json.dumps(warnings))

        with TemporaryDirectory() as directory:
            noisy = Path(directory) / "noisy"
            noisy.write_text("#!/bin/sh\nprintf '123456789'\n", encoding="utf-8")
            noisy.chmod(noisy.stat().st_mode | stat.S_IXUSR)
            runner = menu_adapter.ProviderRunner(timeout=0.2, byte_limit=8, line_limit=8, row_limit=8)
            with self.assertRaises(menu_adapter.ProviderError):
                runner([str(noisy)])

    def test_provider_rejects_timeout_nonzero_invalid_utf8_nul_long_lines_and_too_many_rows(self) -> None:
        cases = {
            "timeout": "#!/bin/sh\nsleep 1\n",
            "nonzero": "#!/bin/sh\nexit 9\n",
            "utf8": "#!/bin/sh\nprintf '\\377'\n",
            "nul": "#!/bin/sh\nprintf '\\000'\n",
            "line": "#!/bin/sh\nprintf '123456789'\n",
            "rows": "#!/bin/sh\nprintf 'a\\na\\na\\na\\n'\n",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in cases.items():
                with self.subTest(name=name):
                    script = root / name
                    script.write_text(body, encoding="utf-8")
                    script.chmod(0o755)
                    runner = menu_adapter.ProviderRunner(
                        timeout=0.08, byte_limit=64, line_limit=8, row_limit=3
                    )
                    with self.assertRaises(menu_adapter.ProviderError):
                        runner([str(script)])

    def test_overall_guard_deadline_cleans_up_live_process_groups(self) -> None:
        runner = menu_adapter.GuardRunner(timeout=5)
        entries = {
            str(index): {
                "id": str(index),
                "kind": "action",
                "effective_guards": {
                    "when": "sleep 5",
                    "checked": "",
                    "disabled": "",
                },
            }
            for index in range(12)
        }
        started = time.monotonic()
        with self.assertRaises(menu_adapter.GuardDeadlineExceeded):
            menu_adapter.evaluate_guards(
                entries, runner, per_guard_timeout=5, overall_timeout=0.1
            )
        self.assertLess(time.monotonic() - started, 0.7)
        self.assertEqual(runner.active_count, 0)

    def test_executor_validates_every_payload_before_spawn(self) -> None:
        calls: list[object] = []

        def spawn(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return object()

        malformed = (
            {},
            {"mode": "argv", "argv": []},
            {"mode": "argv", "argv": ["true\0bad"]},
            {"mode": "shell", "command": ""},
            {"mode": "script", "script": "/bin/true", "args": []},
            {"mode": "script", "script": "../escape", "args": []},
        )
        with TemporaryDirectory() as directory:
            for payload in malformed:
                with self.subTest(payload=payload), self.assertRaises(menu_adapter.ActionUnavailable):
                    menu_adapter.execute_payload(payload, adapter_dir=Path(directory), popen=spawn)
        self.assertEqual(calls, [])

    def test_executor_rejects_symlink_escape_directory_missing_and_non_executable_scripts(self) -> None:
        calls: list[object] = []
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            outside = root.parent / f"{root.name}-outside"
            outside.write_text("#!/bin/sh\n", encoding="utf-8")
            outside.chmod(0o755)
            (scripts / "escape").symlink_to(outside)
            (scripts / "directory").mkdir()
            plain = scripts / "plain"
            plain.write_text("#!/bin/sh\n", encoding="utf-8")
            payloads = (
                {"mode": "script", "script": "scripts/escape", "args": []},
                {"mode": "script", "script": "scripts/directory", "args": []},
                {"mode": "script", "script": "scripts/missing", "args": []},
                {"mode": "script", "script": "scripts/plain", "args": []},
            )
            for payload in payloads:
                with self.subTest(payload=payload), self.assertRaises(menu_adapter.ActionUnavailable):
                    menu_adapter.execute_payload(
                        payload,
                        adapter_dir=root,
                        popen=lambda *args, **kwargs: calls.append((args, kwargs)),
                    )
            outside.unlink()
        self.assertEqual(calls, [])

    def test_executor_maps_any_process_start_exception_without_payload_leakage(self) -> None:
        def fail_start(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("PRIVATE_START_DETAIL")

        with self.assertRaises(menu_adapter.ActionStartError) as caught:
            menu_adapter.execute_payload(
                {"mode": "argv", "argv": ["true"]},
                popen=fail_start,
            )
        self.assertNotIn("PRIVATE_START_DETAIL", str(caught.exception))


class CliEndToEndTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict[str, str], Path]:
        system = root / "system.jsonc"
        extension = root / "missing-extension.jsonc"
        compatibility = root / "compatibility.json"
        marker = root / "marker"
        script_dir = root / "scripts"
        script_dir.mkdir()
        fixture = script_dir / "fixture"
        fixture.write_text(
            "#!/bin/sh\nprintf marker > \"$1\"\ni=0; while [ $i -lt 2000 ]; do printf noisy; i=$((i+1)); done\nsleep 0.4\n",
            encoding="utf-8",
        )
        fixture.chmod(0o755)
        _write(
            system,
            {
                "safe": {"label": "Safe", "action": "stock-safe"},
                "hidden": {"label": "Hidden", "action": "stock-hidden", "when": "false"},
                "disabled": {"label": "Disabled", "action": "stock-disabled", "disabled": "true"},
                "menu": {"label": "Menu"},
            },
        )
        rules = {}
        for menu_id in ("safe", "hidden", "disabled"):
            rules[menu_id] = {
                "match": {"action": f"stock-{menu_id}", "provider": ""},
                "mode": "mapped",
                "dispatch": {"mode": "script", "script": "scripts/fixture", "args": [str(marker)]},
            }
        _write(compatibility, {"schemaVersion": 1, "omarchyPackage": "fixture", "rules": rules})
        env = dict(os.environ)
        env.update(
            OMARCHY_MENU_SYSTEM_SOURCE=str(system),
            OMARCHY_MENU_EXTENSION_SOURCE=str(extension),
            OMARCHY_MENU_COMPATIBILITY=str(compatibility),
            OMARCHY_MENU_ADAPTER_DIR=str(root),
        )
        return env, marker

    def test_render_and_detached_dispatch_work_from_outside_project(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as cwd:
            env, marker = self._fixture(Path(directory))
            rendered = subprocess.run(
                [sys.executable, str(ADAPTER), "render"], cwd=cwd, env=env,
                text=True, capture_output=True, timeout=3,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertEqual(rendered.stderr, "")
            model = json.loads(rendered.stdout)
            safe = model["entries"]["safe"]
            started = time.monotonic()
            dispatched = subprocess.run(
                [sys.executable, str(ADAPTER), "dispatch", model["revision"], "safe", safe["actionToken"]],
                cwd=cwd, env=env, text=True, capture_output=True, timeout=1,
            )
            elapsed = time.monotonic() - started
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
            self.assertEqual(dispatched.stdout, "")
            self.assertEqual(dispatched.stderr, "")
            self.assertLess(elapsed, 0.3)
            deadline = time.monotonic() + 1
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(marker.read_text(), "marker")

    def test_audit_reports_inventory_and_exits_nonzero_when_incomplete(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            env, marker = self._fixture(root)
            complete = subprocess.run(
                [sys.executable, str(ADAPTER), "audit"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
            )
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertTrue(json.loads(complete.stdout)["ok"])
            compatibility = Path(env["OMARCHY_MENU_COMPATIBILITY"])
            document = json.loads(compatibility.read_text(encoding="utf-8"))
            del document["rules"]["safe"]
            _write(compatibility, document)
            incomplete = subprocess.run(
                [sys.executable, str(ADAPTER), "audit"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
            )
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertEqual(json.loads(incomplete.stdout)["missing"], ["safe"])
            self.assertFalse(marker.exists())

    def test_every_rejected_selection_keeps_spawn_marker_zero_and_errors_are_redacted(self) -> None:
        with TemporaryDirectory() as directory:
            env, marker = self._fixture(Path(directory))
            render = subprocess.run([sys.executable, str(ADAPTER), "render"], env=env, text=True, capture_output=True, timeout=3)
            model = json.loads(render.stdout)
            cases = (
                ("old", "safe", model["entries"]["safe"]["actionToken"]),
                (model["revision"], "safe", "old-token"),
                (model["revision"], "unknown", "token"),
                (model["revision"], "menu", "token"),
                (model["revision"], "hidden", "token"),
                (model["revision"], "disabled", "token"),
            )
            for revision, menu_id, token in cases:
                with self.subTest(menu_id=menu_id, revision=revision):
                    result = subprocess.run(
                        [sys.executable, str(ADAPTER), "dispatch", revision, menu_id, token],
                        env=env, text=True, capture_output=True, timeout=3,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    record = json.loads(result.stderr)
                    self.assertEqual(set(record) - {"id"}, {"category", "code"})
                    self.assertLessEqual(len(result.stderr), 512)
                    self.assertNotIn("stock-", result.stderr)
                    self.assertFalse(marker.exists())

    def test_stock_render_exposes_the_ten_approved_root_categories(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ADAPTER), "render"],
            text=True,
            capture_output=True,
            timeout=12,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        model = json.loads(result.stdout)
        labels = [
            model["entries"][menu_id]["label"]
            for menu_id in model["entries"]["root"]["children"]
        ]
        self.assertEqual(
            labels,
            ["Apps", "Learn", "Trigger", "Style", "Setup", "Install", "Remove", "Update", "About", "System"],
        )


if __name__ == "__main__":
    unittest.main()
