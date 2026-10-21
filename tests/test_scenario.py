import json
import os
import unittest

from common_ground import fair_share, measured, outings
from tests.test_outings import counter

PATH = os.path.join(os.path.dirname(__file__), "..", "scenarios", "friday-table.json")
IMPLIED = {"film": "urn:entity:movie", "band": "urn:entity:artist", "book": "urn:entity:book",
           "show": "urn:entity:tv_show", "restaurant": "urn:entity:place", "brand": "urn:entity:brand"}


class SampleGroup(unittest.TestCase):
    def setUp(self):
        with open(PATH, encoding="utf-8") as fh:
            self.data = json.load(fh)

    def test_four_fictional_people_with_two_favourites_from_two_different_domains(self):
        self.assertIn("fictional", self.data["label"])
        self.assertEqual([m["name"] for m in self.data["members"]], ["Noor", "Owen", "Pia", "Quinn"])
        for member in self.data["members"]:
            domains = [f["domain"] for f in member["favourites"]]
            with self.subTest(member["name"]):
                self.assertEqual(len(domains), 2)
                self.assertEqual(len(set(domains)), 2)

    def test_each_domain_implies_a_type_the_search_asks_for(self):
        for member in self.data["members"]:
            for favourite in member["favourites"]:
                self.assertIn(IMPLIED[favourite["domain"]], measured.FAVOURITE_TYPES)

    def test_no_favourite_is_a_person_and_all_are_short_public_names(self):
        names = [f["name"] for m in self.data["members"] for f in m["favourites"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(0 < len(n) <= outings.MAX_FAVOURITE for n in names))
        self.assertNotIn("person", {f["domain"] for m in self.data["members"] for f in m["favourites"]})
        self.assertEqual(len(names), 8)

    def test_the_conditions_are_the_plans(self):
        self.assertEqual((self.data["day"], self.data["price_min"], self.data["price_max"]), ("friday", 2, 3))
        self.assertEqual(self.data["place_text"], measured.SAMPLE_CITY)
        self.assertEqual(self.data["kind_query"], "restaurant")

    def test_it_opens_as_an_outing_inside_the_default_call_limit(self):
        token = counter()
        doc, ws = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
        doc, out = outings.open_outing(doc, ws, outings.scenario_args(self.data), token=token, now=0.0)
        opened = outings.outing(doc, ws, out)
        self.assertEqual(opened["budget"]["limit"], fair_share.CALL_LIMIT_DEFAULT)
        searches = sum(len(m["favourites"]) for m in opened["members"])
        self.assertEqual(searches + 1 + 1 + len(opened["members"]), 14)


if __name__ == "__main__":
    unittest.main()
