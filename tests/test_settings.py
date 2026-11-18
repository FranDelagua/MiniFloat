import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.settings import SettingsError, WindowSettings, load_settings, settings_path


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "MiniFloat" / "settings.json"

    def test_creates_defaults_and_reloads_them(self) -> None:
        self.assertEqual(load_settings(self.path), WindowSettings())
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"window": {"always_on_top": True, "opacity": 0.92}},
        )
        self.assertEqual(load_settings(self.path), WindowSettings())

    def test_loads_user_values_and_preserves_existing_file(self) -> None:
        self.path.parent.mkdir()
        original = '{"window": {"always_on_top": false, "opacity": 0.6}, "other": 1}'
        self.path.write_text(original, encoding="utf-8")
        self.assertEqual(load_settings(self.path), WindowSettings(False, 0.6))
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_missing_values_are_added_without_losing_other_data(self) -> None:
        self.path.parent.mkdir()
        self.path.write_text(
            '{"window": {"always_on_top": false, "extra": 7}, "other": 1}',
            encoding="utf-8",
        )
        self.assertEqual(load_settings(self.path), WindowSettings(False, 0.92))
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"window": {"always_on_top": False, "opacity": 0.92, "extra": 7}, "other": 1},
        )

    def test_invalid_configuration_is_not_overwritten(self) -> None:
        self.path.parent.mkdir()
        invalid_documents = (
            "{",
            "[]",
            '{"window": []}',
            '{"window": {"always_on_top": 1}}',
            '{"window": {"opacity": true}}',
            '{"window": {"opacity": 0.59}}',
            '{"window": {"opacity": 1.01}}',
            '{"window": {"opacity": NaN}}',
            '{"window": {"opacity": 1e500}}',
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                self.path.write_text(document, encoding="utf-8")
                with self.assertRaises(SettingsError):
                    load_settings(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), document)

    def test_save_failure_preserves_existing_configuration(self) -> None:
        self.path.parent.mkdir()
        original = '{"window": {"always_on_top": false}}'
        self.path.write_text(original, encoding="utf-8")
        with patch("app.settings.os.replace", side_effect=OSError("write failed")):
            with self.assertRaises(SettingsError):
                load_settings(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_path_uses_local_app_data(self) -> None:
        with patch.dict("os.environ", {"LOCALAPPDATA": self.directory.name}):
            self.assertEqual(settings_path(), self.path)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SettingsError):
                settings_path()


if __name__ == "__main__":
    unittest.main()
