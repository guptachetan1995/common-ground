import unittest
from unittest import mock

from common_ground import measured
from common_ground.refusal import Refusal


class Measured(unittest.TestCase):
    def test_every_constant_the_probe_fixes_exists(self):
        for name in (
            "FAVOURITE_TYPES", "TYPES_FORM", "CONDITIONS_OK", "SAMPLE_CITY", "LONG_LIST", "AFFINITY_PATH",
            "EXPLAIN_PATH", "LEAN_PATH", "AFFINITY_SCALE", "RESPONSE_SHAPES",
        ):
            with self.subTest(name):
                self.assertTrue(hasattr(measured, name))

    def test_everything_starts_unverified_and_names_real_constants(self):
        self.assertTrue(measured.UNVERIFIED)
        for name in measured.UNVERIFIED:
            self.assertTrue(hasattr(measured, name), name)
        self.assertEqual(len(measured.UNVERIFIED), 10)

    def test_the_documented_defaults(self):
        self.assertEqual(measured.LONG_LIST, 50)
        self.assertEqual(measured.TYPES_FORM, "comma")
        self.assertEqual(measured.SAMPLE_CITY, "New York City")
        self.assertEqual(measured.AFFINITY_PATH, ("query", "affinity"))
        self.assertEqual(set(measured.CONDITIONS_OK), {"location", "day", "price", "kind"})
        self.assertEqual(measured.CONDITIONS_OK["location"], "filter.location.query")

    def test_favourites_are_never_people(self):
        self.assertNotIn("urn:entity:person", measured.FAVOURITE_TYPES)
        self.assertTrue(all(t.startswith("urn:entity:") for t in measured.FAVOURITE_TYPES))
        self.assertNotIn("person", " ".join(measured.FAVOURITE_TYPES))

    def test_a_live_source_is_refused_while_anything_is_unverified(self):
        with self.assertRaises(Refusal) as caught:
            measured.require_verified()
        self.assertEqual(caught.exception.code, "shapes_unverified")
        self.assertIn("LONG_LIST", caught.exception.detail)

    def test_it_is_allowed_once_the_probe_has_emptied_the_set(self):
        with mock.patch.object(measured, "UNVERIFIED", frozenset()):
            measured.require_verified()

    def test_the_probe_fixes_what_is_unmeasured(self):
        self.assertIsNone(measured.AFFINITY_SCALE)
        self.assertEqual(measured.RESPONSE_SHAPES, frozenset())


if __name__ == "__main__":
    unittest.main()
