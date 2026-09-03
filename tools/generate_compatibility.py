#!/usr/bin/env python3
"""Regenerate the audited compatibility inventory from the installed stock menu."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import menu_adapter  # noqa: E402


STOCK_MENU = Path("/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc")
OUTPUT = PROJECT_ROOT / "compatibility.json"


def argv(*values: str, env: dict[str, str] | None = None) -> dict[str, object]:
    dispatch: dict[str, object] = {"mode": "argv", "argv": list(values)}
    if env is not None:
        dispatch["env"] = env
    return {"dispatch": dispatch}


def script(path: str) -> dict[str, object]:
    return {"dispatch": {"mode": "script", "script": path, "args": []}}


MAPPED = {
    "apps": argv("noctalia", "msg", "panel-open", "launcher"),
    "learn.keybindings": argv("niri", "msg", "action", "show-hotkey-overlay"),
    "trigger.capture.screenshot": argv("niri", "msg", "action", "screenshot"),
    "trigger.capture.text": script("scripts/capture-text"),
    "trigger.capture.qr": script("scripts/capture-qr"),
    "trigger.capture.color": argv("niri", "msg", "pick-color"),
    "trigger.capture.screenrecord.no-audio": argv(
        "omarchy-capture-screenrecording",
        env={"OMARCHY_SCREENRECORD_USE_PORTAL": "true"},
    ),
    "trigger.capture.screenrecord.desktop-audio": argv(
        "omarchy-capture-screenrecording",
        "--with-desktop-audio",
        env={"OMARCHY_SCREENRECORD_USE_PORTAL": "true"},
    ),
    "trigger.capture.screenrecord.microphone": argv(
        "omarchy-capture-screenrecording",
        "--with-desktop-audio",
        "--with-microphone-audio",
        env={"OMARCHY_SCREENRECORD_USE_PORTAL": "true"},
    ),
    "trigger.toggle.idle-lock": argv("noctalia", "msg", "caffeine-toggle"),
    "trigger.toggle.notifications": argv(
        "noctalia", "msg", "notification-dnd-toggle"
    ),
    "trigger.toggle.nightlight": argv(
        "noctalia", "msg", "nightlight-force-toggle"
    ),
    "trigger.toggle.top-bar": argv("noctalia", "msg", "bar-toggle"),
    "trigger.toggle.battery-percentage": argv(
        "noctalia", "msg", "settings-open", "bar"
    ),
    "style.theme": argv("noctalia", "msg", "settings-open", "appearance"),
    "style.background": argv("noctalia", "msg", "panel-toggle", "wallpaper"),
    "style.bar.transparency": argv("noctalia", "msg", "settings-open", "bar"),
    "style.bar.position.top": argv("noctalia", "msg", "settings-open", "bar"),
    "style.bar.position.bottom": argv("noctalia", "msg", "settings-open", "bar"),
    "style.bar.position.left": argv("noctalia", "msg", "settings-open", "bar"),
    "style.bar.position.right": argv("noctalia", "msg", "settings-open", "bar"),
    "setup.monitors": {
        "dispatch": {
            "mode": "shell",
            "command": 'omarchy-launch-config-editor "$HOME/.config/niri/config.kdl"',
        },
        "when": "",
    },
    "setup.keybindings": {
        "dispatch": {
            "mode": "shell",
            "command": 'omarchy-launch-config-editor "$HOME/.config/niri/config.kdl"',
        },
        "when": "",
    },
    "setup.input": {
        "dispatch": {
            "mode": "shell",
            "command": 'omarchy-launch-config-editor "$HOME/.config/niri/config.kdl"',
        },
        "when": "",
    },
    "system.lock": argv("noctalia", "msg", "session", "lock"),
    "system.logout": argv(
        "niri", "msg", "action", "quit", "--skip-confirmation"
    ),
    "system.reboot": script("scripts/system-reboot"),
    "system.shutdown": script("scripts/system-shutdown"),
}

DISABLED = {
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

SCRIPT_REQUIREMENTS = {
    "scripts/capture-text": ["slurp", "grim", "tesseract", "wl-copy"],
    "scripts/capture-qr": ["slurp", "grim", "zbarimg", "wl-copy"],
    "scripts/system-reboot": ["systemd-run", "systemctl", "niri"],
    "scripts/system-shutdown": ["systemd-run", "systemctl", "niri"],
}

PROVIDER_REQUIREMENTS = {
    "fonts": [
        "omarchy-font-list",
        "omarchy-font-current",
        "fc-list",
        "pkill",
        "pgrep",
        "omarchy-hook",
        "omarchy-notification-send",
    ],
}


def mapped_requirements(rule: dict[str, object]) -> list[str]:
    dispatch = rule.get("dispatch")
    if not isinstance(dispatch, dict):
        return []
    if dispatch.get("mode") == "argv":
        values = dispatch.get("argv")
        return [values[0]] if isinstance(values, list) and values else []
    if dispatch.get("mode") == "shell":
        return ["omarchy-launch-config-editor"]
    if dispatch.get("mode") == "script":
        return list(SCRIPT_REQUIREMENTS.get(str(dispatch.get("script")), []))
    return []


HELPER_PATTERN = re.compile(r"\bomarchy-[A-Za-z0-9_-]+\b")
FONT_PROVIDER_HELPERS = (
    "omarchy-font-list",
    "omarchy-font-current",
    "omarchy-font-set",
    "omarchy-notification-send",
    "omarchy-hook",
)


def helper_dependency_closure(
    command: str, *, recursive: bool = True
) -> tuple[dict[str, str], list[str]]:
    pending = sorted(set(HELPER_PATTERN.findall(command)))
    direct = set(pending)
    visited: set[str] = set()
    digests: dict[str, str] = {}
    unresolved: list[str] = []

    while pending:
        name = pending.pop(0)
        if name in visited:
            continue
        visited.add(name)
        path = Path("/usr/bin") / name
        if not path.is_file():
            # Direct action tokens are commands by construction.  Recursive
            # script text can also contain IDs, package names, temp paths, and
            # examples that merely look like helper names, so only existing
            # /usr/bin helpers belong to the executable closure.
            if name in direct:
                unresolved.append(name)
            continue
        content = path.read_bytes()
        digests[str(path)] = hashlib.sha256(content).hexdigest()
        if recursive:
            dependencies = HELPER_PATTERN.findall(content.decode(errors="ignore"))
            for dependency in sorted(set(dependencies)):
                if (
                    dependency not in visited
                    and (Path("/usr/bin") / dependency).is_file()
                ):
                    pending.append(dependency)

    return dict(sorted(digests.items())), sorted(unresolved)


def opaque_runtime_text(menu_id: str, rule: dict[str, object]) -> str:
    if rule["mode"] == "pass-through":
        match = rule.get("match", {})
        return str(match.get("action", "")) if isinstance(match, dict) else ""
    if rule["mode"] == "mapped":
        dispatch = rule.get("dispatch", {})
        if not isinstance(dispatch, dict):
            return ""
        if dispatch.get("mode") == "argv":
            values = dispatch.get("argv", [])
            return " ".join(values) if isinstance(values, list) else ""
        if dispatch.get("mode") == "shell":
            return str(dispatch.get("command", ""))
    if menu_id == "style.font":
        # This filtered closure mirrors the local font-set wrapper's execution
        # path while deliberately excluding stock omarchy-restart-shell.
        return " ".join(FONT_PROVIDER_HELPERS)
    return ""


def main() -> None:
    source = menu_adapter.load_source(STOCK_MENU)
    rules: dict[str, dict[str, object]] = {}
    for menu_id, fields in source.items():
        action = fields.get("action", "")
        provider = fields.get("provider", "")
        if not action and not provider:
            continue
        rule: dict[str, object] = {
            "match": {"action": action, "provider": provider},
            "mode": "provider" if provider else "pass-through",
        }
        if menu_id in MAPPED:
            rule.update(MAPPED[menu_id])
            rule["mode"] = "mapped"
            rule["requires"] = mapped_requirements(rule)
        elif provider:
            rule["requires"] = list(PROVIDER_REQUIREMENTS.get(str(provider), []))
        for reason, disabled_ids in DISABLED.items():
            if menu_id in disabled_ids:
                rule.update(mode="disabled", reason=reason, force_visible=True)
        runtime_text = opaque_runtime_text(menu_id, rule)
        if HELPER_PATTERN.search(runtime_text):
            digests, unresolved = helper_dependency_closure(
                runtime_text, recursive=menu_id != "style.font"
            )
            rule["digests"] = digests
            if unresolved:
                rule.update(
                    mode="disabled",
                    reason="Compatibility not reviewed",
                    force_visible=True,
                    unresolvedHelpers=unresolved,
                )
        rules[menu_id] = rule

    document = {
        "schemaVersion": 1,
        "stockSource": str(STOCK_MENU),
        "omarchyPackage": "omarchy-dev 4.0.0.r2014.gf99d33a-1",
        "rules": rules,
    }
    OUTPUT.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
