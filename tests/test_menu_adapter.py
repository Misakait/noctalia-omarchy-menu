from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import menu_adapter


class JsoncParsingTests(unittest.TestCase):
    def test_comments_and_trailing_commas_do_not_damage_strings(self) -> None:
        document = r'''
        {
          // a real comment
          "url": "https://example.test/a//b",
          "markers": "literal /* text */ and // text",
          "nested": {
            "value": 7, /* another real comment */
          },
        }
        '''

        self.assertEqual(
            menu_adapter.parse_jsonc(document),
            {
                "url": "https://example.test/a//b",
                "markers": "literal /* text */ and // text",
                "nested": {"value": 7},
            },
        )


class SourceMergeTests(unittest.TestCase):
    def test_extension_overrides_fields_without_erasing_omitted_fields(self) -> None:
        defaults = {
            "about": {
                "icon": "i",
                "label": "About",
                "action": "omarchy-launch-about",
            },
            "system": {"label": "System"},
        }
        extension = {
            "about": {"label": "About this computer"},
            "personal": {"label": "Personal"},
        }

        merged = menu_adapter.merge_sources(defaults, extension)

        self.assertEqual(list(merged), ["about", "system", "personal"])
        self.assertEqual(
            merged["about"],
            {
                "icon": "i",
                "label": "About this computer",
                "action": "omarchy-launch-about",
            },
        )

    def test_explicit_empty_extension_field_clears_default(self) -> None:
        merged = menu_adapter.merge_sources(
            {"about": {"label": "About", "action": "omarchy-launch-about"}},
            {"about": {"action": ""}},
        )

        self.assertEqual(merged["about"]["action"], "")


class NormalizationTests(unittest.TestCase):
    def test_dotted_ids_infer_hierarchy_and_kind(self) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "system": {"label": "System"},
                "system.lock": {"label": "Lock", "action": "lock-now"},
                "power": {"label": "Power", "target": "system"},
            }
        )

        self.assertEqual(entries["root"]["kind"], "menu")
        self.assertEqual(entries["system"]["parent"], "root")
        self.assertEqual(entries["system"]["kind"], "menu")
        self.assertEqual(entries["system.lock"]["parent"], "system")
        self.assertEqual(entries["system.lock"]["kind"], "action")
        self.assertEqual(entries["power"]["kind"], "link")
        self.assertEqual(entries["power"]["target"], "system")

    def test_normalization_preserves_aliases_title_and_source_order(self) -> None:
        entries = menu_adapter.normalize_menu(
            {
                "first": {
                    "label": "First",
                    "title": "First Menu",
                    "aliases": ["one", "1"],
                },
                "second": {"label": "Second"},
            }
        )

        self.assertEqual(entries["first"]["title"], "First Menu")
        self.assertEqual(entries["first"]["aliases"], ["one", "1"])
        self.assertLess(entries["first"]["order"], entries["second"]["order"])


class SourceLoadingTests(unittest.TestCase):
    def test_items_wrapper_is_supported(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "menu.jsonc"
            path.write_text('{"items": {"apps": {"label": "Apps"}}}', encoding="utf-8")

            self.assertEqual(
                menu_adapter.load_source(path),
                {"apps": {"label": "Apps"}},
            )

    def test_invalid_json_reports_source_and_line(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "broken.jsonc"
            path.write_text('{\n  "apps":,\n}', encoding="utf-8")

            with self.assertRaisesRegex(
                menu_adapter.SourceError,
                rf"{path}.*line 2",
            ):
                menu_adapter.load_source(path)

    def test_missing_optional_source_is_empty(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonc"

            self.assertEqual(menu_adapter.load_source(path, required=False), {})


if __name__ == "__main__":
    unittest.main()
