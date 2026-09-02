#!/usr/bin/env python3
"""Adapter between Omarchy's JSONC menu and a Noctalia panel."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from copy import deepcopy
from pathlib import Path
from typing import Callable


class SourceError(ValueError):
    """A menu source could not be loaded or did not have the expected shape."""


class DispatchRejected(ValueError):
    """A requested row is not the same enabled action that was rendered."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"dispatch rejected: {reason}")


class GuardDeadlineExceeded(RuntimeError):
    """The guard batch exceeded its deadline, so its model is unsafe to use."""


def _strip_jsonc_comments(document: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(document):
        char = document[index]
        next_char = document[index + 1] if index + 1 < len(document) else ""

        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
        elif char == "/" and next_char == "/":
            output.extend("  ")
            index += 2
            while index < len(document) and document[index] not in "\r\n":
                output.append(" ")
                index += 1
        elif char == "/" and next_char == "*":
            output.extend("  ")
            index += 2
            while index < len(document):
                if index + 1 < len(document) and document[index : index + 2] == "*/":
                    output.extend("  ")
                    index += 2
                    break
                output.append(document[index] if document[index] in "\r\n" else " ")
                index += 1
        else:
            output.append(char)
            index += 1

    return "".join(output)


def _strip_trailing_commas(document: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False

    for index, char in enumerate(document):
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            output.append(char)
            continue

        if char == ",":
            cursor = index + 1
            while cursor < len(document) and document[cursor].isspace():
                cursor += 1
            previous = index - 1
            while previous >= 0 and document[previous].isspace():
                previous -= 1
            if (
                previous >= 0
                and document[previous] not in ":,[{"
                and cursor < len(document)
                and document[cursor] in "}]"
            ):
                output.append(" ")
                continue

        output.append(char)

    return "".join(output)


def parse_jsonc(document: str) -> object:
    return json.loads(_strip_trailing_commas(_strip_jsonc_comments(document)))


def load_source(path: Path, *, required: bool = True) -> dict[str, dict[str, object]]:
    if not path.exists():
        if not required:
            return {}
        raise SourceError(f"Menu source does not exist: {path}")

    try:
        document = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError(f"Unable to read menu source {path}: {exc}") from exc

    try:
        parsed = parse_jsonc(document)
    except json.JSONDecodeError as exc:
        raise SourceError(
            f"Invalid JSONC in {path} at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    if not isinstance(parsed, dict):
        raise SourceError(f"Menu source {path} must contain an object")

    items = parsed.get("items", parsed)
    if not isinstance(items, dict):
        raise SourceError(f"Menu source {path} field 'items' must contain an object")

    normalized: dict[str, dict[str, object]] = {}
    for menu_id, fields in items.items():
        if not isinstance(menu_id, str) or not isinstance(fields, dict):
            raise SourceError(
                f"Menu source {path} entries must map string IDs to objects"
            )
        normalized[menu_id] = dict(fields)
    return normalized


def merge_sources(
    defaults: dict[str, dict[str, object]],
    extension: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    merged = {menu_id: dict(fields) for menu_id, fields in defaults.items()}
    for menu_id, fields in extension.items():
        if menu_id in merged:
            merged[menu_id].update(fields)
        else:
            merged[menu_id] = dict(fields)
    return merged


def audit_inventory(
    source: dict[str, dict[str, object]],
    compatibility: dict[str, object],
) -> dict[str, object]:
    """Compare stock signatures to the inventory without evaluating or dispatching."""

    raw_rules = compatibility.get("rules")
    rules = raw_rules if isinstance(raw_rules, dict) else {}
    stock = {
        menu_id: fields
        for menu_id, fields in source.items()
        if _string(fields.get("action")) or _string(fields.get("provider"))
    }
    allowed_modes = ("pass-through", "mapped", "provider", "disabled")
    counts = {mode: 0 for mode in allowed_modes}
    missing: list[str] = []
    signature_mismatches: list[str] = []
    invalid_classifications: list[str] = []
    digest_mismatches: list[str] = []

    for menu_id, fields in stock.items():
        rule = rules.get(menu_id)
        if not isinstance(rule, dict):
            missing.append(menu_id)
            continue
        mode = _string(rule.get("mode"))
        if mode not in counts:
            invalid_classifications.append(menu_id)
            continue
        counts[mode] += 1
        expected_action, expected_provider = _expected_signature(rule)
        if (
            expected_action != _string(fields.get("action"))
            or expected_provider != _string(fields.get("provider"))
        ):
            signature_mismatches.append(menu_id)
        if rule_digest_mismatches(rule):
            digest_mismatches.append(menu_id)

    extra = sorted(set(rules) - set(stock))
    problems = (
        missing
        + signature_mismatches
        + invalid_classifications
        + digest_mismatches
        + extra
    )
    return {
        "ok": not problems,
        "stockRows": len(stock),
        "counts": counts,
        "missing": sorted(missing),
        "signatureMismatches": sorted(signature_mismatches),
        "invalidClassifications": sorted(invalid_classifications),
        "digestMismatches": sorted(digest_mismatches),
        "extra": extra,
        "omarchyPackage": _string(compatibility.get("omarchyPackage")),
    }


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def normalize_menu(
    source: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {
        "root": {
            "id": "root",
            "parent": "",
            "kind": "menu",
            "icon": "",
            "iconFont": "",
            "label": "Go",
            "title": "",
            "target": "",
            "description": "",
            "action": "",
            "provider": "",
            "aliases": [],
            "when": "",
            "checked": "",
            "disabled": "",
            "order": -1,
        }
    }

    for order, (menu_id, raw) in enumerate(source.items()):
        action = _string(raw.get("action"))
        target = _string(raw.get("target"))
        parent_value = raw.get("parent")
        if isinstance(parent_value, str):
            parent = parent_value
        elif "." in menu_id:
            parent = menu_id.rsplit(".", 1)[0]
        else:
            parent = "root"

        aliases_value = raw.get("aliases", [])
        if isinstance(aliases_value, str):
            aliases = [aliases_value] if aliases_value else []
        elif isinstance(aliases_value, list):
            aliases = [value for value in aliases_value if isinstance(value, str) and value]
        else:
            aliases = []

        entries[menu_id] = {
            "id": menu_id,
            "parent": parent,
            "kind": "action" if action else ("link" if target else "menu"),
            "icon": _string(raw.get("icon")),
            "iconFont": _string(raw.get("iconFont")),
            "label": _string(raw.get("label")) or menu_id,
            "title": _string(raw.get("title")),
            "target": target,
            "description": _string(raw.get("description")),
            "action": action,
            "provider": _string(raw.get("provider")),
            "aliases": aliases,
            "when": _string(raw.get("when")),
            "checked": _string(raw.get("checked")),
            "disabled": _string(raw.get("disabled")),
            "order": order,
        }

    return entries


_HYPRLAND_PATTERNS = (
    re.compile(r"(^|\s)(hyprctl|hyprpicker)(\s|$)"),
    re.compile(r"omarchy-hyprland-"),
    re.compile(r"(?:^|[/~$])\.config/hypr/"),
    re.compile(r"\bomarchy-shell\b"),
    re.compile(r"\bomarchy-(?:restart|refresh)-(?:shell|hypr[^\s]*)\b"),
    re.compile(r"\bomarchy-bar\b"),
    re.compile(r"\bomarchy-menu-(?:select|images|file|plugin)\b"),
    re.compile(r"\bomarchy-plugin-(?:add|clone|enable|disable|remove|list)\b"),
)


def _expected_signature(rule: dict[str, object]) -> tuple[str, str]:
    match = rule.get("match")
    if isinstance(match, dict):
        action = _string(match.get("action"))
        provider = _string(match.get("provider"))
    else:
        action = _string(rule.get("expected_action"))
        provider = _string(rule.get("expected_provider"))
    return action, provider


def _obviously_incompatible(action: str) -> bool:
    return any(pattern.search(action) for pattern in _HYPRLAND_PATTERNS)


def _file_sha256(path: Path) -> str | None:
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def rule_digest_mismatches(rule: dict[str, object]) -> list[str]:
    """Return audited helper paths whose content is missing or changed."""

    digests = rule.get("digests")
    if digests is None:
        return []
    if not isinstance(digests, dict):
        return ["<invalid-digest-map>"]

    mismatches: list[str] = []
    for raw_path, expected in digests.items():
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            mismatches.append("<invalid-digest-entry>")
        elif _file_sha256(Path(raw_path)) != expected:
            mismatches.append(raw_path)
    return mismatches


def _rule_dispatch(rule: dict[str, object], action: str) -> dict[str, object] | None:
    mode = _string(rule.get("mode"))
    if mode == "mapped":
        nested = rule.get("dispatch")
        if not isinstance(nested, dict):
            return None
        nested_mode = _string(nested.get("mode"))
        if nested_mode == "argv":
            argv = nested.get("argv")
            if isinstance(argv, list) and argv and all(
                isinstance(value, str) for value in argv
            ):
                payload: dict[str, object] = {"mode": "argv", "argv": list(argv)}
                env = nested.get("env")
                if isinstance(env, dict) and all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in env.items()
                ):
                    payload["env"] = dict(env)
                return payload
        if nested_mode == "script":
            script = _string(nested.get("script"))
            args = nested.get("args", [])
            if script and isinstance(args, list) and all(
                isinstance(value, str) for value in args
            ):
                return {"mode": "script", "script": script, "args": list(args)}
        if nested_mode == "shell":
            command = _string(nested.get("command"))
            if command:
                return {"mode": "shell", "command": command}
        return None
    if mode in {"disable", "disabled"}:
        return None
    if mode in {"replace", "argv"}:
        argv = rule.get("argv")
        if isinstance(argv, list) and all(isinstance(value, str) for value in argv):
            payload: dict[str, object] = {"mode": "argv", "argv": list(argv)}
            env = rule.get("env")
            if isinstance(env, dict) and all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in env.items()
            ):
                payload["env"] = dict(env)
            return payload
        return None
    if mode == "script":
        script = _string(rule.get("script"))
        args = rule.get("args", [])
        if script and isinstance(args, list) and all(isinstance(value, str) for value in args):
            return {"mode": "script", "script": script, "args": list(args)}
        return None
    if mode == "shell":
        command = _string(rule.get("command")) or action
        return {"mode": "shell", "command": command} if command else None
    if mode in {"pass-through", "passthrough"}:
        return {"mode": "shell", "command": action} if action else None
    return None


def resolve_compatibility(
    entry: dict[str, object],
    exact_rules: dict[str, dict[str, object]],
    *,
    source: str,
    dependency_available: Callable[[str], bool] | None = None,
) -> dict[str, object]:
    """Resolve an entry before guards are evaluated.

    Rules are signature checked, so changing an action/provider in the user
    extension never inherits an old stock decision merely because its ID stayed
    the same.
    """

    resolved = deepcopy(entry)
    action = _string(entry.get("action"))
    provider = _string(entry.get("provider"))
    source_guards = {
        name: _string(entry.get(name)) for name in ("when", "checked", "disabled")
    }
    resolved["effective_guards"] = source_guards
    resolved["compatibility_status"] = "neutral"
    resolved["compatibility_disabled"] = False
    resolved["force_visible"] = False
    resolved["disabled_reason"] = ""
    resolved.pop("dispatch", None)

    rule = exact_rules.get(_string(entry.get("id")))
    exact = False
    if isinstance(rule, dict):
        expected_action, expected_provider = _expected_signature(rule)
        exact = action == expected_action and provider == expected_provider

    if exact and rule is not None:
        mode = _string(rule.get("mode"))
        for name in ("when", "checked", "disabled"):
            if name in rule:
                resolved["effective_guards"][name] = _string(rule.get(name))
        resolved["force_visible"] = bool(rule.get("force_visible", False))
        if rule_digest_mismatches(rule):
            resolved["compatibility_status"] = "disabled"
            resolved["compatibility_disabled"] = True
            resolved["force_visible"] = True
            resolved["disabled_reason"] = "Compatibility not reviewed"
            return resolved
        requires = rule.get("requires", [])
        checker = dependency_available or (
            lambda name: shutil.which(name) is not None
        )
        if isinstance(requires, list) and all(
            isinstance(name, str) and name for name in requires
        ):
            missing = next((name for name in requires if not checker(name)), "")
            if missing:
                resolved["compatibility_status"] = "disabled"
                resolved["compatibility_disabled"] = True
                resolved["force_visible"] = True
                resolved["disabled_reason"] = f"Missing dependency: {missing}"
                return resolved
        if mode in {"disable", "disabled"}:
            resolved["compatibility_status"] = "disabled"
            resolved["compatibility_disabled"] = True
            resolved["disabled_reason"] = _string(rule.get("reason")) or "Unsupported"
        elif mode in {"native-fonts", "native-power", "provider"}:
            resolved["compatibility_status"] = "provider"
            resolved["provider_mode"] = mode
        else:
            payload = _rule_dispatch(rule, action)
            if payload is None and (action or provider):
                resolved["compatibility_status"] = "disabled"
                resolved["compatibility_disabled"] = True
                resolved["disabled_reason"] = "Compatibility rule invalid"
            else:
                resolved["compatibility_status"] = (
                    "pass-through"
                    if mode in {"pass-through", "passthrough"}
                    else "mapped"
                )
                if payload is not None:
                    resolved["dispatch"] = payload
                    if mode == "mapped" and provider:
                        resolved["kind"] = "action"
        return resolved

    if isinstance(rule, dict) and source == "system":
        resolved["compatibility_status"] = "disabled"
        resolved["compatibility_disabled"] = True
        resolved["force_visible"] = True
        resolved["disabled_reason"] = "Compatibility not reviewed"
        return resolved

    if _obviously_incompatible(action):
        resolved["compatibility_status"] = "disabled"
        resolved["compatibility_disabled"] = True
        resolved["force_visible"] = True
        resolved["disabled_reason"] = "Hyprland only"
    elif provider:
        resolved["compatibility_status"] = "disabled"
        resolved["compatibility_disabled"] = True
        resolved["force_visible"] = True
        resolved["disabled_reason"] = "Unsupported provider"
    elif not action:
        return resolved
    elif source == "extension":
        resolved["compatibility_status"] = "user-pass-through"
        resolved["dispatch"] = {"mode": "shell", "command": action}
    else:
        resolved["compatibility_status"] = "disabled"
        resolved["compatibility_disabled"] = True
        resolved["force_visible"] = True
        resolved["disabled_reason"] = "Compatibility not reviewed"
    return resolved


def expand_providers(
    entries: dict[str, dict[str, object]],
    runner: Callable[[list[str]], str],
) -> dict[str, dict[str, object]]:
    """Expand supported read-only providers without dispatching a selection."""

    expanded = deepcopy(entries)
    next_order = 1 + max(
        (
            int(entry.get("order", -1))
            for entry in expanded.values()
            if isinstance(entry.get("order"), int)
        ),
        default=-1,
    )
    for parent_id, parent in list(expanded.items()):
        if parent.get("compatibility_status") != "provider":
            continue
        provider = _string(parent.get("provider"))
        if provider != "fonts":
            parent["compatibility_status"] = "disabled"
            parent["compatibility_disabled"] = True
            parent["force_visible"] = True
            parent["disabled_reason"] = "Unsupported provider"
            continue
        try:
            listed = runner(["omarchy-font-list"])
            current = runner(["omarchy-font-current"]).strip()
        except Exception:
            parent["compatibility_status"] = "disabled"
            parent["compatibility_disabled"] = True
            parent["force_visible"] = True
            parent["disabled_reason"] = "Provider unavailable: fonts"
            continue

        fonts = list(
            dict.fromkeys(
                value.strip()
                for value in listed.splitlines()
                if value.strip() and "\x00" not in value
            )
        )
        for font in fonts:
            suffix = hashlib.sha256(font.encode("utf-8")).hexdigest()[:24]
            menu_id = f"{parent_id}.provider-{suffix}"
            expanded[menu_id] = {
                "id": menu_id,
                "parent": parent_id,
                "kind": "action",
                "icon": _string(parent.get("icon")),
                "iconFont": _string(parent.get("iconFont")),
                "label": font,
                "title": "",
                "target": "",
                "description": "",
                "action": "",
                "provider": "",
                "aliases": [],
                "when": "",
                "checked": "",
                "disabled": "",
                "order": next_order,
                "effective_guards": {"when": "", "checked": "", "disabled": ""},
                "compatibility_status": "provider",
                "compatibility_disabled": False,
                "force_visible": False,
                "disabled_reason": "",
                "provider_checked": font == current,
                "dispatch": {
                    "mode": "script",
                    "script": "scripts/font-set",
                    "args": [font],
                },
            }
            next_order += 1
    return expanded


def evaluate_guards(
    entries: dict[str, dict[str, object]],
    runner: Callable[[str], bool],
    *,
    per_guard_timeout: float = 1.5,
    overall_timeout: float = 8.0,
    max_workers: int = 8,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Evaluate unique guard expressions concurrently and apply safe defaults."""

    evaluated = deepcopy(entries)
    expressions: set[str] = set()
    for entry in evaluated.values():
        guards = entry.get("effective_guards")
        if not isinstance(guards, dict):
            guards = {
                name: _string(entry.get(name))
                for name in ("when", "checked", "disabled")
            }
            entry["effective_guards"] = guards
        for value in guards.values():
            if isinstance(value, str) and value:
                expressions.add(value)

    results: dict[str, tuple[bool, bool]] = {}
    executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8)))
    started = time.monotonic()
    overall_deadline = started + max(0.0, overall_timeout)
    guard_timeout = max(0.0, per_guard_timeout)
    futures = {
        executor.submit(runner, expression): (expression, time.monotonic())
        for expression in expressions
    }
    pending = set(futures)

    def deadline_for(future: Future[bool]) -> float:
        _expression, submitted = futures[future]
        return min(submitted + guard_timeout, overall_deadline)

    def record_completed(done: set[Future[bool]]) -> None:
        for future in done:
            expression, _submitted = futures[future]
            try:
                results[expression] = (bool(future.result(timeout=0)), True)
            except Exception:
                results[expression] = (False, False)
            pending.remove(future)

    while pending:
        record_completed({future for future in pending if future.done()})
        if not pending:
            break

        now = time.monotonic()
        if now >= overall_deadline:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise GuardDeadlineExceeded("overall guard deadline exceeded")

        for future in tuple(pending):
            expression, submitted = futures[future]
            if now >= deadline_for(future):
                results[expression] = (False, False)
                future.cancel()
                pending.remove(future)

        if not pending:
            break

        next_deadline = min(deadline_for(future) for future in pending)
        done, _ = wait(pending, timeout=max(0.0, next_deadline - time.monotonic()))
        record_completed(done)
    executor.shutdown(wait=False, cancel_futures=True)

    warnings: list[str] = []
    for menu_id, entry in evaluated.items():
        guards = entry["effective_guards"]

        def guard(name: str, default: bool) -> tuple[bool, bool]:
            expression = _string(guards.get(name))
            if not expression:
                return default, True
            return results.get(expression, (False, False))

        when_value, _when_ok = guard("when", True)
        checked_value, _checked_ok = guard(
            "checked", bool(entry.get("provider_checked", False))
        )
        disabled_value, disabled_ok = guard("disabled", False)
        force_visible = bool(entry.get("force_visible", False))
        compatibility_disabled = bool(entry.get("compatibility_disabled", False))

        entry["visible"] = force_visible or when_value
        entry["checked_state"] = checked_value or (disabled_value and disabled_ok)
        entry["disabled_state"] = compatibility_disabled or (
            disabled_value and disabled_ok
        )
        entry["enabled"] = bool(entry["visible"]) and not bool(entry["disabled_state"])
        if _string(guards.get("disabled")) and not disabled_ok:
            warnings.append(f"{menu_id}: disabled guard unavailable")

    return evaluated, warnings


def finalize_tree(entries: dict[str, dict[str, object]]) -> dict[str, object]:
    """Build a navigable tree while containing malformed extensions."""

    normalized = deepcopy(entries)
    warnings: list[str] = []
    if "root" not in normalized:
        raise SourceError("Normalized menu is missing its root")

    for entry in normalized.values():
        entry["children"] = []
        entry["header"] = _string(entry.get("title")) or _string(entry.get("label"))
        entry["breadcrumb"] = []
        entry["search_text"] = ""
        entry.setdefault("visible", True)
        entry.setdefault("enabled", bool(entry["visible"]))
        entry.setdefault("checked_state", False)
        entry.setdefault("disabled_state", False)

    invalid: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def validate_parent(menu_id: str) -> bool:
        if menu_id == "root":
            return True
        if menu_id in invalid:
            return False
        if menu_id in visited:
            return True
        if menu_id in visiting:
            invalid.update(visiting)
            warnings.append("Hierarchy cycle detected")
            return False
        visiting.add(menu_id)
        parent = _string(normalized[menu_id].get("parent")) or "root"
        if parent not in normalized:
            invalid.add(menu_id)
            warnings.append(f"Orphan menu entry: {menu_id}")
            valid = False
        else:
            valid = validate_parent(parent)
            if not valid:
                invalid.add(menu_id)
        visiting.discard(menu_id)
        visited.add(menu_id)
        return valid

    for menu_id in list(normalized):
        validate_parent(menu_id)

    for menu_id, entry in normalized.items():
        if menu_id == "root" or menu_id in invalid:
            continue
        parent = _string(entry.get("parent")) or "root"
        normalized[parent]["children"].append(menu_id)

    for entry in normalized.values():
        entry["children"].sort(key=lambda child: int(normalized[child].get("order", 0)))

    link_state: dict[str, bool] = {}
    link_stack: set[str] = set()

    def target_valid(menu_id: str) -> bool:
        if menu_id in link_state:
            return link_state[menu_id]
        if menu_id in link_stack:
            warnings.append("Link target cycle detected")
            for cycle_id in link_stack:
                link_state[cycle_id] = False
                invalid.add(cycle_id)
            return False
        entry = normalized.get(menu_id)
        if entry is None or menu_id in invalid:
            return False
        if _string(entry.get("kind")) != "link":
            return True
        target = _string(entry.get("target"))
        if not target or target not in normalized:
            warnings.append(f"Orphan link target: {menu_id}")
            link_state[menu_id] = False
            invalid.add(menu_id)
            return False
        link_stack.add(menu_id)
        valid = target_valid(target)
        link_stack.discard(menu_id)
        link_state[menu_id] = valid
        if not valid:
            invalid.add(menu_id)
        return valid

    for menu_id, entry in normalized.items():
        if _string(entry.get("kind")) == "link":
            target_valid(menu_id)

    visibility_cache: dict[str, bool] = {}
    visibility_stack: set[str] = set()

    def visible(menu_id: str) -> bool:
        if menu_id in visibility_cache:
            return visibility_cache[menu_id]
        if menu_id in invalid or menu_id in visibility_stack:
            return False
        entry = normalized[menu_id]
        base = bool(entry.get("visible", True))
        if not base:
            visibility_cache[menu_id] = False
            return False
        visibility_stack.add(menu_id)
        kind = _string(entry.get("kind"))
        if menu_id == "root":
            value = True
        elif kind == "action":
            value = True
        elif kind == "link":
            target = _string(entry.get("target"))
            value = target in normalized and visible(target)
        elif _string(entry.get("provider")):
            value = True
        else:
            value = any(visible(child) for child in entry["children"])
        visibility_stack.discard(menu_id)
        visibility_cache[menu_id] = value
        return value

    for menu_id, entry in normalized.items():
        is_visible = visible(menu_id)
        entry["visible"] = is_visible
        entry["enabled"] = is_visible and not bool(entry.get("disabled_state", False))

    for entry in normalized.values():
        entry["children"] = [
            child for child in entry["children"] if normalized[child]["visible"]
        ]

    def decorate_reachable(menu_id: str, ancestors: list[str]) -> None:
        entry = normalized[menu_id]
        breadcrumb = (
            ancestors
            if menu_id == "root"
            else ancestors + [_string(entry.get("header"))]
        )
        entry["breadcrumb"] = breadcrumb
        aliases = entry.get("aliases", [])
        alias_terms = (
            [alias for alias in aliases if isinstance(alias, str)]
            if isinstance(aliases, list)
            else []
        )
        entry["search_text"] = " ".join(
            term.casefold()
            for term in [*breadcrumb, _string(entry.get("description")), *alias_terms]
            if term
        )
        for child in entry["children"]:
            decorate_reachable(child, breadcrumb)

    decorate_reachable("root", [])

    return {"root": "root", "entries": normalized, "warnings": warnings}


def search_entries(model: dict[str, object], menu_id: str, query: str) -> list[str]:
    entries = model.get("entries")
    if not isinstance(entries, dict) or menu_id not in entries:
        return []
    needle = query.casefold().strip()
    if not needle:
        return []

    queue = list(entries[menu_id].get("children", []))
    found: list[str] = []
    while queue:
        current = queue.pop(0)
        entry = entries.get(current)
        if not isinstance(entry, dict) or not entry.get("visible"):
            continue
        queue.extend(entry.get("children", []))
        if entry.get("kind") != "action" or not entry.get("enabled"):
            continue
        aliases = entry.get("aliases", [])
        terms = [_string(entry.get("label")), _string(entry.get("description"))]
        if isinstance(aliases, list):
            terms.extend(value for value in aliases if isinstance(value, str))
        if needle in " ".join(terms).casefold():
            found.append(current)
    return found


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_revision(source: object, compatibility: object) -> str:
    return _canonical_digest({"source": source, "compatibility": compatibility})


def action_token(entry: dict[str, object]) -> str:
    return _canonical_digest(
        {"id": _string(entry.get("id")), "dispatch": entry.get("dispatch")}
    )


def build_view_model(tree: dict[str, object], revision: str) -> dict[str, object]:
    entries = tree.get("entries", {})
    public_entries: dict[str, dict[str, object]] = {}
    allowed = (
        "id",
        "parent",
        "kind",
        "icon",
        "iconFont",
        "label",
        "title",
        "target",
        "description",
        "aliases",
        "provider",
        "header",
        "children",
        "visible",
        "enabled",
        "checked_state",
        "disabled_state",
        "compatibility_status",
        "disabled_reason",
        "order",
        "breadcrumb",
        "search_text",
    )
    if isinstance(entries, dict):
        for menu_id, entry in entries.items():
            if not isinstance(menu_id, str) or not isinstance(entry, dict):
                continue
            public = {key: deepcopy(entry[key]) for key in allowed if key in entry}
            public["checked"] = bool(public.pop("checked_state", False))
            public["disabled"] = bool(public.pop("disabled_state", False))
            public["compatibilityStatus"] = public.pop(
                "compatibility_status", "neutral"
            )
            public["disabledReason"] = public.pop("disabled_reason", "")
            if entry.get("dispatch") is not None and entry.get("kind") == "action":
                public["actionToken"] = action_token(entry)
            public_entries[menu_id] = public

    return {
        "schemaVersion": 1,
        "revision": revision,
        "root": tree.get("root", "root"),
        "entries": public_entries,
        "warnings": list(tree.get("warnings", [])),
    }


def validate_dispatch(
    entries: dict[str, dict[str, object]],
    *,
    current_revision: str,
    requested_revision: str,
    menu_id: str,
    requested_token: str,
) -> dict[str, object]:
    if requested_revision != current_revision:
        raise DispatchRejected("stale")
    entry = entries.get(menu_id)
    if entry is None:
        raise DispatchRejected("unknown")
    if entry.get("kind") != "action" or entry.get("dispatch") is None:
        raise DispatchRejected("not-actionable")
    if not entry.get("visible", False):
        raise DispatchRejected("hidden")
    if not entry.get("enabled", False) or entry.get("disabled_state", False):
        raise DispatchRejected("disabled")
    if requested_token != action_token(entry):
        raise DispatchRejected("stale")
    return deepcopy(entry["dispatch"])
