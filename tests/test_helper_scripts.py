from __future__ import annotations

import os
import stat
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


class CaptureHelperTests(unittest.TestCase):
    def test_text_capture_copies_ocr_output_without_hyprland_freeze(self) -> None:
        script = SCRIPTS / "capture-text"
        self.assertTrue(script.is_file(), "capture-text helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            clipboard = root / "clipboard"
            trace = root / "trace"
            _write_executable(bin_dir / "slurp", 'echo "10,20 300x200"\n')
            _write_executable(
                bin_dir / "grim",
                'printf "grim:%s\\n" "$*" >>"$TRACE"\nprintf png-bytes\n',
            )
            _write_executable(
                bin_dir / "tesseract",
                'cat >/dev/null\nprintf "recognized text"\n',
            )
            _write_executable(bin_dir / "wl-copy", 'cat >"$CLIPBOARD"\n')
            env = os.environ | {
                "PATH": f"{bin_dir}:/usr/bin",
                "TRACE": str(trace),
                "CLIPBOARD": str(clipboard),
                "OMARCHY_OCR_LANGS": "eng+jpn",
            }

            completed = subprocess.run(
                [str(script)],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(clipboard.read_text(encoding="utf-8"), "recognized text")
            self.assertEqual(
                trace.read_text(encoding="utf-8"), "grim:-g 10,20 300x200 -\n"
            )
            self.assertEqual(completed.stdout, "")

    def test_qr_capture_marks_clipboard_sensitive_and_never_prints_value(self) -> None:
        script = SCRIPTS / "capture-qr"
        self.assertTrue(script.is_file(), "capture-qr helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            clipboard = root / "clipboard"
            trace = root / "trace"
            _write_executable(bin_dir / "slurp", 'echo "1,2 30x40"\n')
            _write_executable(bin_dir / "grim", 'printf png-bytes\n')
            _write_executable(
                bin_dir / "zbarimg",
                'cat >/dev/null\nprintf "otpauth://private-value"\n',
            )
            _write_executable(
                bin_dir / "wl-copy",
                'printf "wl-copy:%s\\n" "$*" >"$TRACE"\ncat >"$CLIPBOARD"\n',
            )
            env = os.environ | {
                "PATH": f"{bin_dir}:/usr/bin",
                "TRACE": str(trace),
                "CLIPBOARD": str(clipboard),
            }

            completed = subprocess.run(
                [str(script)],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                clipboard.read_text(encoding="utf-8"), "otpauth://private-value"
            )
            self.assertEqual(trace.read_text(encoding="utf-8"), "wl-copy:--sensitive\n")
            self.assertNotIn("private-value", completed.stdout + completed.stderr)


class PowerHelperTests(unittest.TestCase):
    def test_power_helpers_request_system_action_without_quitting_niri(self) -> None:
        for operation in ("reboot", "poweroff"):
            with self.subTest(operation=operation):
                script_name = (
                    "system-reboot" if operation == "reboot" else "system-shutdown"
                )
                script = SCRIPTS / script_name
                self.assertTrue(
                    script.is_file(), f"{script_name} helper must be shipped"
                )
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    bin_dir = root / "bin"
                    bin_dir.mkdir()
                    trace = root / "trace"
                    _write_executable(
                        bin_dir / "systemctl",
                        'printf "systemctl:%s\\n" "$*" >>"$TRACE"\n',
                    )
                    _write_executable(
                        bin_dir / "systemd-run",
                        'printf "systemd-run:%s\\n" "$*" >>"$TRACE"\n',
                    )
                    _write_executable(
                        bin_dir / "niri",
                        'printf "niri:%s\\n" "$*" >>"$TRACE"\n',
                    )
                    env = os.environ | {
                        "PATH": f"{bin_dir}:/usr/bin",
                        "TRACE": str(trace),
                    }

                    completed = subprocess.run(
                        [str(script)],
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=3,
                        check=False,
                    )

                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(
                        trace.read_text(encoding="utf-8").splitlines(),
                        [f"systemctl:{operation} --no-wall"],
                    )


class PasswordlessSudoHelperTests(unittest.TestCase):
    def _environment(self, root: Path) -> tuple[dict[str, str], Path, Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        trace = root / "trace"
        trace.touch()
        grant = root / f"etc/sudoers.d/99-omarchy-nopasswd-{os.environ['USER']}"

        _write_executable(bin_dir / "gum", 'printf "gum:%s\\n" "$*" >>"$TRACE"\n')
        _write_executable(
            bin_dir / "visudo",
            'printf "visudo:%s\\n" "$*" >>"$TRACE"\n',
        )
        _write_executable(
            bin_dir / "sudo",
            r'''printf "sudo:%s\n" "$*" >>"$TRACE"
if [[ ${1:-} == "-n" ]]; then
    shift
fi
if [[ ${1:-} == "-k" || ${1:-} == "-v" ]]; then
    exit 0
fi
command=${1:-}
shift || true
case "$command" in
    test)
        /usr/bin/test "$@"
        ;;
    visudo|systemctl)
        exit 0
        ;;
    install)
        args=()
        while (($#)); do
            case "$1" in
                -o|-g)
                    shift 2
                    ;;
                *)
                    args+=("$1")
                    shift
                    ;;
            esac
        done
        /usr/bin/install "${args[@]}"
        ;;
    rm)
        /usr/bin/rm "$@"
        ;;
    *)
        exit 64
        ;;
esac
''',
        )
        env = os.environ | {
            "PATH": f"{bin_dir}:/usr/bin",
            "TRACE": str(trace),
            "OMARCHY_MENU_TEST_ROOT": str(root),
        }
        return env, trace, grant

    def test_nonterminal_invocation_opens_a_dedicated_terminal(self) -> None:
        script = SCRIPTS / "passwordless-sudo-toggle"
        self.assertTrue(script.is_file(), "passwordless sudo helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            trace = root / "trace"
            _write_executable(
                bin_dir / "xdg-terminal-exec",
                'printf "%s\\n" "$*" >"$TRACE"\n',
            )
            env = os.environ | {
                "PATH": f"{bin_dir}:/usr/bin",
                "TRACE": str(trace),
            }

            completed = subprocess.run(
                [str(script)],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                trace.read_text(encoding="utf-8"),
                " ".join(
                    (
                        "--app-id=org.omarchy.terminal",
                        "--title=Boot-scoped Passwordless Sudo",
                        "--",
                        str(script),
                        "--terminal\n",
                    )
                ),
            )

    def test_enable_survives_without_timer_and_second_run_disables(self) -> None:
        script = SCRIPTS / "passwordless-sudo-toggle"
        self.assertTrue(script.is_file(), "passwordless sudo helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cleanup = root / "etc/tmpfiles.d/omarchy-nopasswd-sudo.conf"
            cleanup.parent.mkdir(parents=True)
            (root / "etc/sudoers.d").mkdir(parents=True)
            cleanup.write_text(
                "r! /etc/sudoers.d/99-omarchy-nopasswd-*\n",
                encoding="utf-8",
            )
            env, trace, grant = self._environment(root)

            enabled = subprocess.run(
                [str(script), "--terminal"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            self.assertEqual(
                grant.read_text(encoding="utf-8"),
                f"{os.environ['USER']} ALL=(ALL) NOPASSWD: ALL\n",
            )
            self.assertEqual(stat.S_IMODE(grant.stat().st_mode), 0o440)
            self.assertNotIn("systemd-run", trace.read_text(encoding="utf-8"))
            self.assertNotIn("on-active", trace.read_text(encoding="utf-8"))

            disabled = subprocess.run(
                [str(script), "--terminal"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertFalse(grant.exists())
            self.assertIn("sudo:-k", trace.read_text(encoding="utf-8"))

    def test_enable_fails_closed_without_boot_cleanup_rule(self) -> None:
        script = SCRIPTS / "passwordless-sudo-toggle"
        self.assertTrue(script.is_file(), "passwordless sudo helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc/sudoers.d").mkdir(parents=True)
            env, trace, grant = self._environment(root)

            completed = subprocess.run(
                [str(script), "--terminal"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(grant.exists())
            calls = trace.read_text(encoding="utf-8")
            self.assertNotIn("sudo:visudo", calls)
            self.assertNotIn("sudo:install", calls)
            self.assertNotIn("visudo:", calls)

    def test_higher_priority_cleanup_override_cannot_borrow_vendor_rule(self) -> None:
        script = SCRIPTS / "passwordless-sudo-toggle"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            override = root / "etc/tmpfiles.d/omarchy-nopasswd-sudo.conf"
            vendor = root / "usr/lib/tmpfiles.d/omarchy-nopasswd-sudo.conf"
            override.parent.mkdir(parents=True)
            vendor.parent.mkdir(parents=True)
            (root / "etc/sudoers.d").mkdir(parents=True)
            override.write_text("# Disabled locally\n", encoding="utf-8")
            vendor.write_text(
                "r! /etc/sudoers.d/99-omarchy-nopasswd-*\n",
                encoding="utf-8",
            )
            env, _trace, grant = self._environment(root)

            completed = subprocess.run(
                [str(script), "--terminal"],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(grant.exists())


class FontHelperTests(unittest.TestCase):
    def test_font_set_updates_without_shell_restart_or_injection(self) -> None:
        script = SCRIPTS / "font-set"
        self.assertTrue(script.is_file(), "font-set helper must be shipped")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            bin_dir = root / "bin"
            home.mkdir()
            bin_dir.mkdir()
            marker = root / "injected"
            font_name = f"Test & Mono; touch {marker}"
            trace = root / "trace"
            configs = {
                home / ".config/alacritty/alacritty.toml": 'family = "Old Font"\n',
                home / ".config/kitty/kitty.conf": "font_family Old Font\n",
                home / ".config/ghostty/config": 'font-family = "Old Font"\n',
                home / ".config/foot/foot.ini": "font=Old Font:size=8\n",
            }
            for path, content in configs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            _write_executable(bin_dir / "fc-list", 'printf "%s\\n" "$FONT_NAME"\n')
            _write_executable(
                bin_dir / "pkill", 'printf "pkill:%s\\n" "$*" >>"$TRACE"\n'
            )
            _write_executable(bin_dir / "pgrep", "exit 1\n")
            _write_executable(
                bin_dir / "omarchy-hook",
                'printf "hook:%s|%s\\n" "$1" "$2" >>"$TRACE"\n',
            )
            _write_executable(
                bin_dir / "omarchy-restart-shell",
                'touch "$RESTARTED"\n',
            )
            env = os.environ | {
                "HOME": str(home),
                "PATH": f"{bin_dir}:/usr/bin",
                "FONT_NAME": font_name,
                "TRACE": str(trace),
                "RESTARTED": str(root / "restarted"),
            }

            completed = subprocess.run(
                [str(script), font_name],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((root / "restarted").exists())
            self.assertIn(
                f'family = "{font_name}"',
                (home / ".config/alacritty/alacritty.toml").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                f"font_family {font_name}",
                (home / ".config/kitty/kitty.conf").read_text(encoding="utf-8"),
            )
            self.assertIn(
                f"font={font_name}:size=9",
                (home / ".config/foot/foot.ini").read_text(encoding="utf-8"),
            )
            fontconfig = (home / ".config/fontconfig/fonts.conf").read_text(
                encoding="utf-8"
            )
            self.assertIn("Test &amp; Mono; touch", fontconfig)
            self.assertNotIn("<string>Test & Mono; touch", fontconfig)
            self.assertIn("pkill:-USR1 kitty", trace.read_text(encoding="utf-8"))
            self.assertIn("pkill:-SIGUSR2 ghostty", trace.read_text(encoding="utf-8"))
            self.assertIn(f"hook:font-set|{font_name}", trace.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
