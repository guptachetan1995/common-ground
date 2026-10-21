import json
import os
import re
import unittest

from common_ground import measured

ROOT = os.path.join(os.path.dirname(__file__), "..")
SKIP_DIRS = {".git", "__pycache__", ".cache", "out", "node_modules", ".venv"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
RESERVED = "00000000-0000-4000-8000-"
KEY_HEADER_VALUE = re.compile(r"x-api-key\"?[:=] *[\"']?[A-Za-z0-9_-]{20,}", re.I)
KEY_ASSIGNED = re.compile("QLOO_API_KEY" + r"=[A-Za-z0-9_-]{8,}")
DEMOGRAPHICS = "signal." + "demographics"
CODE_SUFFIXES = (".py", ".js", ".html", ".css", ".json")
REFUSAL_TEST = os.path.join("tests", "test_request_building.py")
THIS_FILE = os.path.join("tests", "test_repo_has_no_qloo_responses.py")


def tracked_text():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            private = name == ".env" or (name.startswith(".env.") and name != ".env.example")
            if private or name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    yield os.path.relpath(path, ROOT), fh.read()
            except UnicodeDecodeError:
                continue


class NoQlooData(unittest.TestCase):
    def test_every_uuid_shaped_id_is_in_the_reserved_range(self):
        for path, text in tracked_text():
            for found in UUID.findall(text):
                with self.subTest(path=path, found=found):
                    self.assertTrue(found.startswith(RESERVED))

    def test_no_key_value_anywhere(self):
        for path, text in tracked_text():
            if path in ("verify.sh", THIS_FILE):
                continue
            with self.subTest(path=path):
                self.assertIsNone(KEY_HEADER_VALUE.search(text))
                self.assertIsNone(KEY_ASSIGNED.search(text))

    def test_the_example_settings_are_all_empty(self):
        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines() if line and not line.startswith("#")]
        self.assertTrue(lines)
        self.assertTrue(all(line.endswith("=") for line in lines), lines)

    def test_scenario_files_hold_names_only(self):
        folder = os.path.join(ROOT, "scenarios")
        allowed = {
            "label", "when", "place_text", "day", "price_min", "price_max", "kind_query", "members", "name",
            "favourites", "domain",
        }

        def keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        files = [f for f in os.listdir(folder) if f.endswith(".json")]
        self.assertTrue(files)
        for name in files:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                data = json.load(fh)
            with self.subTest(file=name):
                self.assertLessEqual(set(keys(data)), allowed)

    def test_measured_holds_no_uuid_shaped_string(self):
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in list(value) + list(value.values()):
                    yield from strings(item)
            elif isinstance(value, (tuple, list, set, frozenset)):
                for item in value:
                    yield from strings(item)

        for name in dir(measured):
            if name.isupper():
                for text in strings(getattr(measured, name)):
                    with self.subTest(name=name):
                        self.assertIsNone(UUID.search(text))
        with open(measured.__file__, encoding="utf-8") as fh:
            self.assertIsNone(UUID.search(fh.read()))

    def test_no_demographic_signal_outside_the_refusal_test(self):
        for path, text in tracked_text():
            if path.endswith(CODE_SUFFIXES) and path not in (REFUSAL_TEST, THIS_FILE):
                with self.subTest(path=path):
                    self.assertNotIn(DEMOGRAPHICS, text)

    def test_every_fixture_says_it_is_synthetic(self):
        folder = os.path.join(ROOT, "tests", "fixtures", "synthetic")
        for name in os.listdir(folder):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                with self.subTest(fixture=name):
                    self.assertIn("Synthetic", json.load(fh)["_label"])


if __name__ == "__main__":
    unittest.main()
