"""Core behavioral contract for the Omarchy menu adapter.

These tests deliberately exercise only pure model/validation functions.  They never
spawn a configured action.  The implementation API expected by this suite is:

``resolve_compatibility(entry, exact_rules, *, source)``
    Return a copied entry with ``effective_guards`` (``when``, ``checked``, and
    ``disabled``), ``compatibility_status``, ``compatibility_disabled``,
    ``force_visible``, ``disabled_reason``, and an internal ``dispatch`` payload.

``evaluate_guards(entries, runner, ...)``
    Return ``(entries, warnings)``.  ``runner(expression)`` returns truthiness or
    raises on command failure/timeout.  Output entries expose ``visible``,
    ``checked_state``, ``disabled_state``, and ``enabled``.
    ``GuardDeadlineExceeded`` means no partial guard model may be used.

``finalize_tree(entries)`` and ``search_entries(model, menu_id, query)``
    Return a model containing ``root``, ``entries``, and non-fatal ``warnings``;
    search returns ordered matching leaf IDs in the active subtree.

``compute_revision(source, compatibility)``, ``action_token(entry)``,
``build_view_model(tree, revision)``, and ``validate_dispatch(...)``
    Produce opaque freshness values and validate a selection without launching it.
    Rejections raise ``DispatchRejected`` carrying a stable ``reason`` attribute.
"""

from __future__ import annotations

import json
import time
import unittest
from collections import Counter

import menu_adapter


def _entry(
    menu_id: str,
    *,
    when: str = "",
    checked: str = "",
    disabled: str = "",
    compatibility_disabled: bool = False,
    force_visible: bool = False,
) -> dict[str, object]:
    return {
        "id": menu_id,
        "kind": "action",
        "label": menu_id,
        "effective_guards": {
            "when": when,
            "checked": checked,
            "disabled": disabled,
        },
        "compatibility_disabled": compatibility_disabled,
        "force_visible": force_visible,
        "disabled_reason": "Hyprland only" if compatibility_disabled else "",
        "dispatch": {"mode": "argv", "argv": ["safe-test-action", menu_id]},
    }


def _mark_guard_state(
    entries: dict[str, dict[str, object]],
    *,
    hidden: set[str] | None = None,
    disabled: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    hidden = hidden or set()
    disabled = disabled or set()
    for menu_id, entry in entries.items():
        entry["visible"] = menu_id not in hidden
        entry["checked_state"] = False
        entry["disabled_state"] = menu_id in disabled
        entry["enabled"] = menu_id not in hidden and menu_id not in disabled
    return entries


class GuardEvaluationTests(unittest.TestCase):
    def test_successful_guards_set_visibility_checked_and_disabled_state(self) -> None:
        values = {
            "yes": True,
            "no": False,
            "checked": True,
            "blocked": True,
        }
        entries = {
            "visible": _entry("visible", when="yes", checked="checked"),
            "hidden": _entry("hidden", when="no"),
            "disabled": _entry("disabled", disabled="blocked"),
        }

        evaluated, warnings = menu_adapter.evaluate_guards(
            entries, lambda expression: values[expression]
        )

        self.assertTrue(evaluated["visible"]["visible"])
        self.assertTrue(evaluated["visible"]["checked_state"])
        self.assertTrue(evaluated["visible"]["enabled"])
        self.assertFalse(evaluated["hidden"]["visible"])
        self.assertFalse(evaluated["hidden"]["enabled"])
        self.assertTrue(evaluated["disabled"]["disabled_state"])
        self.assertFalse(evaluated["disabled"]["enabled"])
        self.assertEqual(warnings, [])

    def test_failed_and_timed_out_guards_use_state_specific_safe_defaults(self) -> None:
        def runner(expression: str) -> bool:
            if expression.endswith("timeout"):
                raise TimeoutError(expression)
            raise RuntimeError(expression)

        entries = {
            "when-failed": _entry("when-failed", when="when-failure"),
            "when-timed": _entry("when-timed", when="when-timeout"),
            "checked-failed": _entry("checked-failed", checked="checked-failure"),
            "checked-timed": _entry("checked-timed", checked="checked-timeout"),
            "disabled-failed": _entry(
                "disabled-failed", disabled="disabled-failure"
            ),
            "disabled-timed": _entry(
                "disabled-timed", disabled="disabled-timeout"
            ),
        }

        evaluated, warnings = menu_adapter.evaluate_guards(
            entries,
            runner,
            per_guard_timeout=0.01,
            overall_timeout=0.1,
            max_workers=8,
        )

        self.assertFalse(evaluated["when-failed"]["visible"])
        self.assertFalse(evaluated["when-timed"]["visible"])
        self.assertFalse(evaluated["checked-failed"]["checked_state"])
        self.assertFalse(evaluated["checked-timed"]["checked_state"])
        self.assertFalse(evaluated["disabled-failed"]["disabled_state"])
        self.assertFalse(evaluated["disabled-timed"]["disabled_state"])
        self.assertTrue(evaluated["disabled-failed"]["enabled"])
        self.assertTrue(evaluated["disabled-timed"]["enabled"])
        self.assertTrue(any("disabled-failed" in warning for warning in warnings))
        self.assertTrue(any("disabled-timed" in warning for warning in warnings))
        self.assertTrue(all("failure" not in warning for warning in warnings))
        self.assertTrue(all("timeout" not in warning for warning in warnings))

    def test_identical_guard_expression_is_evaluated_once(self) -> None:
        calls: Counter[str] = Counter()

        def runner(expression: str) -> bool:
            calls[expression] += 1
            return True

        entries = {
            "one": _entry("one", when="shared-expression"),
            "two": _entry("two", checked="shared-expression"),
            "three": _entry("three", disabled="shared-expression"),
        }

        menu_adapter.evaluate_guards(entries, runner)

        self.assertEqual(calls, Counter({"shared-expression": 1}))

    def test_slow_when_guard_uses_its_individual_timeout_not_overall_deadline(
        self,
    ) -> None:
        """A slow visibility probe must not hold the model until the full budget."""

        def runner(_expression: str) -> bool:
            time.sleep(0.06)
            return True

        started = time.monotonic()
        evaluated, _warnings = menu_adapter.evaluate_guards(
            {"slow": _entry("slow", when="slow-expression")},
            runner,
            per_guard_timeout=0.01,
            overall_timeout=0.2,
        )

        self.assertLess(time.monotonic() - started, 0.04)
        self.assertFalse(evaluated["slow"]["visible"])

    def test_overall_deadline_rejects_the_entire_guard_refresh_promptly(self) -> None:
        """An unfinished overall guard batch cannot produce a partial model."""

        def runner(_expression: str) -> bool:
            time.sleep(0.06)
            return True

        started = time.monotonic()
        with self.assertRaises(menu_adapter.GuardDeadlineExceeded):
            menu_adapter.evaluate_guards(
                {
                    "one": _entry("one", when="one-expression"),
                    "two": _entry("two", when="two-expression"),
                },
                runner,
                per_guard_timeout=0.2,
                overall_timeout=0.01,
                max_workers=1,
            )
        self.assertLess(time.monotonic() - started, 0.04)


class CompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stock_action = "hyprctl dispatch exec screenshot-tool"
        self.rule = {
            "capture": {
                "expected_action": self.stock_action,
                "expected_provider": "",
                "mode": "replace",
                "argv": ["niri", "msg", "action", "screenshot"],
                "when": "niri msg version",
                "force_visible": False,
            }
        }

    def test_exact_signature_mapping_precedes_generic_hyprland_detection(self) -> None:
        entry = menu_adapter.normalize_menu(
            {
                "capture": {
                    "label": "Renamed by extension",
                    "action": self.stock_action,
                    "when": "hyprctl version",
                }
            }
        )["capture"]

        resolved = menu_adapter.resolve_compatibility(
            entry, self.rule, source="system"
        )

        self.assertEqual(resolved["compatibility_status"], "mapped")
        self.assertFalse(resolved["compatibility_disabled"])
        self.assertEqual(
            resolved["dispatch"],
            {"mode": "argv", "argv": ["niri", "msg", "action", "screenshot"]},
        )
        self.assertEqual(resolved["effective_guards"]["when"], "niri msg version")

    def test_changed_action_or_provider_signature_bypasses_exact_rule(self) -> None:
        changed_action = menu_adapter.normalize_menu(
            {"capture": {"action": "hyprctl dispatch exec changed"}}
        )["capture"]
        changed_provider = menu_adapter.normalize_menu(
            {
                "capture": {
                    "action": self.stock_action,
                    "provider": "different-provider",
                }
            }
        )["capture"]

        for entry in (changed_action, changed_provider):
            with self.subTest(entry=entry):
                resolved = menu_adapter.resolve_compatibility(
                    entry, self.rule, source="extension"
                )
                self.assertEqual(resolved["compatibility_status"], "disabled")
                self.assertTrue(resolved["compatibility_disabled"])
                self.assertEqual(resolved["disabled_reason"], "Hyprland only")
                self.assertNotEqual(
                    resolved.get("dispatch"),
                    {
                        "mode": "argv",
                        "argv": ["niri", "msg", "action", "screenshot"],
                    },
                )

    def test_source_aware_fallback_trusts_user_action_but_not_unknown_stock_helper(
        self,
    ) -> None:
        stock = menu_adapter.normalize_menu(
            {"new": {"action": "omarchy-future-helper"}}
        )["new"]
        user = menu_adapter.normalize_menu(
            {"personal": {"action": "notify-send hello"}}
        )["personal"]

        stock_result = menu_adapter.resolve_compatibility(stock, {}, source="system")
        user_result = menu_adapter.resolve_compatibility(user, {}, source="extension")

        self.assertTrue(stock_result["compatibility_disabled"])
        self.assertEqual(
            stock_result["disabled_reason"], "Compatibility not reviewed"
        )
        self.assertEqual(user_result["compatibility_status"], "user-pass-through")
        self.assertFalse(user_result["compatibility_disabled"])
        self.assertEqual(
            user_result["dispatch"],
            {"mode": "shell", "command": "notify-send hello"},
        )

    def test_forced_disabled_rule_wins_before_a_failing_when_guard(self) -> None:
        source_action = "omarchy-hyprland-webcam"
        rules = {
            "webcam": {
                "expected_action": source_action,
                "expected_provider": "",
                "mode": "disable",
                "reason": "Hyprland only",
                "force_visible": True,
            }
        }
        entry = menu_adapter.normalize_menu(
            {
                "webcam": {
                    "action": source_action,
                    "when": "hardware-is-present",
                }
            }
        )["webcam"]
        resolved = menu_adapter.resolve_compatibility(entry, rules, source="system")

        evaluated, _warnings = menu_adapter.evaluate_guards(
            {"webcam": resolved}, lambda _expression: False
        )

        self.assertTrue(evaluated["webcam"]["visible"])
        self.assertTrue(evaluated["webcam"]["disabled_state"])
        self.assertFalse(evaluated["webcam"]["enabled"])
        self.assertEqual(evaluated["webcam"]["disabled_reason"], "Hyprland only")


class TreeAndSearchTests(unittest.TestCase):
    def test_reachable_entries_get_safe_breadcrumb_and_search_text(self) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "style": {"label": "Style", "title": "Appearance"},
                "style.wallpaper": {
                    "label": "Wallpaper",
                    "description": "Choose a background",
                    "aliases": ["Backdrop"],
                    "action": "secret-action",
                },
                "orphan": {
                    "parent": "missing",
                    "label": "Orphan",
                    "action": "another-secret-action",
                },
            }
        )
        _mark_guard_state(entries)

        model = menu_adapter.finalize_tree(entries)

        wallpaper = model["entries"]["style.wallpaper"]
        self.assertEqual(wallpaper["breadcrumb"], ["Appearance", "Wallpaper"])
        self.assertEqual(
            wallpaper["search_text"],
            "appearance wallpaper choose a background backdrop",
        )
        self.assertNotIn("secret-action", wallpaper["search_text"])
        self.assertEqual(model["entries"]["orphan"]["breadcrumb"], [])
        self.assertEqual(model["entries"]["orphan"]["search_text"], "")

    def test_menu_and_link_visibility_follows_visible_descendants(self) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "style": {"label": "Style", "title": "Appearance"},
                "style.wallpaper": {"label": "Wallpaper", "action": "safe-wall"},
                "empty": {"label": "Empty"},
                "empty.hidden": {"label": "Hidden", "action": "safe-hidden"},
                "style-link": {"label": "Style Link", "target": "style"},
                "empty-link": {"label": "Empty Link", "target": "empty"},
                "dynamic": {"label": "Dynamic", "provider": "fonts"},
            }
        )
        _mark_guard_state(entries, hidden={"empty.hidden"})

        model = menu_adapter.finalize_tree(entries)

        self.assertTrue(model["entries"]["style"]["visible"])
        self.assertEqual(model["entries"]["style"]["header"], "Appearance")
        self.assertTrue(model["entries"]["style-link"]["visible"])
        self.assertFalse(model["entries"]["empty"]["visible"])
        self.assertFalse(model["entries"]["empty-link"]["visible"])
        self.assertTrue(model["entries"]["dynamic"]["visible"])
        self.assertEqual(
            model["entries"]["root"]["children"],
            ["style", "style-link", "dynamic"],
        )

    def test_orphans_and_hierarchy_or_target_cycles_are_warned_and_unreachable(
        self,
    ) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "orphan": {"parent": "missing", "action": "safe-orphan"},
                "parent-a": {"parent": "parent-b"},
                "parent-b": {"parent": "parent-a"},
                "link-a": {"target": "link-b"},
                "link-b": {"target": "link-a"},
            }
        )
        _mark_guard_state(entries)

        model = menu_adapter.finalize_tree(entries)

        for menu_id in ("orphan", "parent-a", "parent-b", "link-a", "link-b"):
            self.assertFalse(model["entries"][menu_id]["visible"])
            self.assertFalse(model["entries"][menu_id]["enabled"])
        warning_text = " ".join(model["warnings"]).lower()
        self.assertIn("orphan", warning_text)
        self.assertIn("cycle", warning_text)

    def test_search_is_case_insensitive_uses_aliases_and_stays_in_active_subtree(
        self,
    ) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "style": {"label": "Style"},
                "style.wallpaper": {
                    "label": "Wallpaper",
                    "aliases": ["Background", "Backdrop"],
                    "action": "safe-wall",
                },
                "style.hypr": {
                    "label": "Hyprland setting",
                    "aliases": ["background hypr"],
                    "action": "safe-disabled",
                },
                "system": {"label": "System"},
                "system.background": {
                    "label": "Background service",
                    "action": "safe-system",
                },
            }
        )
        _mark_guard_state(entries, disabled={"style.hypr"})
        model = menu_adapter.finalize_tree(entries)

        self.assertEqual(
            menu_adapter.search_entries(model, "style", "bAcKgRoUnD"),
            ["style.wallpaper"],
        )
        self.assertEqual(menu_adapter.search_entries(model, "style", "system"), [])


class FreshnessAndDispatchTests(unittest.TestCase):
    def _action_entry(self, value: str = "balanced") -> dict[str, object]:
        return {
            "id": f"power.{value}",
            "kind": "action",
            "label": value.title(),
            "visible": True,
            "enabled": True,
            "checked_state": False,
            "disabled_state": False,
            "dispatch": {
                "mode": "argv",
                "argv": ["noctalia", "msg", "power-set", value],
            },
        }

    def test_revision_is_stable_and_covers_source_and_compatibility(self) -> None:
        source = {"about": {"action": "omarchy-launch-about"}}
        compatibility = {"about": {"mode": "pass-through"}}

        revision = menu_adapter.compute_revision(source, compatibility)

        self.assertEqual(
            revision,
            menu_adapter.compute_revision(source, compatibility),
        )
        self.assertNotEqual(
            revision,
            menu_adapter.compute_revision(
                {"about": {"action": "changed-command"}}, compatibility
            ),
        )
        self.assertNotEqual(
            revision,
            menu_adapter.compute_revision(
                source, {"about": {"mode": "disable"}}
            ),
        )

    def test_action_token_is_opaque_and_changes_with_provider_value(self) -> None:
        balanced = self._action_entry("balanced")
        performance = self._action_entry("performance")

        balanced_token = menu_adapter.action_token(balanced)

        self.assertNotEqual(balanced_token, menu_adapter.action_token(performance))
        self.assertNotIn("balanced", balanced_token)
        self.assertNotIn("noctalia", balanced_token)

    def test_view_model_contains_token_but_no_raw_dispatch_payload(self) -> None:
        entry = self._action_entry()
        entry["action"] = "super-secret-command --destructive-looking-flag"
        tree = {"root": "root", "entries": {"power.balanced": entry}, "warnings": []}

        view = menu_adapter.build_view_model(tree, "opaque-revision")
        serialized = json.dumps(view, sort_keys=True)

        self.assertEqual(view["revision"], "opaque-revision")
        self.assertIn("actionToken", view["entries"]["power.balanced"])
        self.assertNotIn("dispatch", view["entries"]["power.balanced"])
        self.assertNotIn("action", view["entries"]["power.balanced"])
        self.assertNotIn("super-secret-command", serialized)
        self.assertNotIn("power-set", serialized)

    def test_dispatch_validation_accepts_only_current_enabled_leaf(self) -> None:
        entry = self._action_entry()
        entries = {entry["id"]: entry}
        revision = "current-revision"
        token = menu_adapter.action_token(entry)

        payload = menu_adapter.validate_dispatch(
            entries,
            current_revision=revision,
            requested_revision=revision,
            menu_id=str(entry["id"]),
            requested_token=token,
        )

        self.assertEqual(payload, entry["dispatch"])

    def test_dispatch_rejects_stale_unknown_hidden_disabled_and_non_leaf_rows(
        self,
    ) -> None:
        good = self._action_entry()
        hidden = {**self._action_entry("hidden"), "visible": False}
        disabled = {**self._action_entry("disabled"), "enabled": False}
        submenu = {
            "id": "system",
            "kind": "menu",
            "label": "System",
            "visible": True,
            "enabled": True,
        }
        entries = {
            str(good["id"]): good,
            str(hidden["id"]): hidden,
            str(disabled["id"]): disabled,
            "system": submenu,
        }
        revision = "current-revision"
        good_token = menu_adapter.action_token(good)
        cases = (
            ("old-revision", str(good["id"]), good_token, "stale"),
            (revision, str(good["id"]), "old-token", "stale"),
            (revision, "unknown", good_token, "unknown"),
            (revision, str(hidden["id"]), menu_adapter.action_token(hidden), "hidden"),
            (
                revision,
                str(disabled["id"]),
                menu_adapter.action_token(disabled),
                "disabled",
            ),
            (revision, "system", "irrelevant", "not-actionable"),
        )

        for requested_revision, menu_id, token, reason in cases:
            with self.subTest(reason=reason, menu_id=menu_id):
                with self.assertRaises(menu_adapter.DispatchRejected) as caught:
                    menu_adapter.validate_dispatch(
                        entries,
                        current_revision=revision,
                        requested_revision=requested_revision,
                        menu_id=menu_id,
                        requested_token=token,
                    )
                self.assertEqual(caught.exception.reason, reason)

    def test_changed_provider_value_is_stale_and_errors_do_not_leak_action(self) -> None:
        rendered = self._action_entry("balanced")
        old_token = menu_adapter.action_token(rendered)
        current = self._action_entry("performance")
        current["id"] = rendered["id"]
        current["action"] = "secret-raw-shell-command"

        with self.assertRaises(menu_adapter.DispatchRejected) as caught:
            menu_adapter.validate_dispatch(
                {str(current["id"]): current},
                current_revision="same-source-revision",
                requested_revision="same-source-revision",
                menu_id=str(current["id"]),
                requested_token=old_token,
            )

        self.assertEqual(caught.exception.reason, "stale")
        self.assertNotIn("secret-raw-shell-command", str(caught.exception))
        self.assertNotIn("performance", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
