import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
FOLDERS = ("common_ground", "tests")
LONGEST = 110
# The command line prints by design; this file holds the pattern that finds prints.
PRINTS_ALLOWED_IN = {
    os.path.join("common_ground", "__main__.py"),
    os.path.join("tests", "test_layout_rules.py"),
}


def python_files():
    for folder in FOLDERS:
        for name in sorted(os.listdir(os.path.join(ROOT, folder))):
            if name.endswith(".py"):
                yield os.path.join(folder, name)


class Layout(unittest.TestCase):
    def test_no_tabs_no_trailing_space_no_long_line_no_debug_print(self):
        for path in python_files():
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                text = fh.read()
            self.assertTrue(not text or (text.endswith("\n") and not text.endswith("\n\n")), path)
            for number, line in enumerate(text.split("\n"), 1):
                where = f"{path}:{number}"
                with self.subTest(where):
                    self.assertNotIn("\t", line)
                    self.assertEqual(line, line.rstrip())
                    self.assertLessEqual(len(line), LONGEST)
                    if path not in PRINTS_ALLOWED_IN:
                        self.assertIsNone(re.search(r"(^|[^.\w])print\(|breakpoint\(|import pdb", line))


if __name__ == "__main__":
    unittest.main()
