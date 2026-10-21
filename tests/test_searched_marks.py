"""A favourite remembers that it was searched, so the page can tell "not searched yet" from "Qloo found
nothing", and a member-added favourite waits for a search nobody has run."""
import unittest

from common_ground import sources
from tests.session import Session


class Silent(sources.FakeSource):
    """A source whose search finds nothing for a favourite called Nothing Known."""

    def _search(self, values, types):
        if values["query"] == "Nothing Known":
            return {"results": []}
        return super()._search(values, types)


def sample_with(name):
    return {"members": [
        {"name": "Noor", "favourites": [name, "Dune"]}, {"name": "Owen", "favourites": ["Radiohead"]},
    ]}


class SearchedMarks(unittest.TestCase):
    def test_a_new_favourite_is_not_searched_and_a_search_marks_it_whatever_it_finds(self):
        s = Session(Silent())
        oid = s.open(sample_with("Nothing Known"))
        first = s.outing(oid)["members"][0]["favourites"]
        self.assertEqual([f["searched"] for f in first], [False, False])
        self.assertEqual(s.code("look_up_favourite", {"outing_id": oid, "member_id": "m1",
                                                      "favourite_id": "f1"}), "qloo_no_results")
        s.ok("look_up_favourite", {"outing_id": oid, "member_id": "m1", "favourite_id": "f2"})
        marks = s.outing(oid)["members"][0]["favourites"]
        self.assertEqual([(f["searched"], len(f["candidates"])) for f in marks], [(True, 0), (True, 5)])

    def test_the_refused_search_still_counts_as_a_call_and_leaves_its_trace_line(self):
        s = Session(Silent())
        oid = s.open(sample_with("Nothing Known"))
        s.code("look_up_favourite", {"outing_id": oid, "member_id": "m1", "favourite_id": "f1"})
        out = s.outing(oid)
        self.assertEqual(out["budget"]["spent"], 1)
        self.assertEqual(out["trace"][-1]["outcome"], "qloo_no_results")

    def test_a_favourite_added_later_is_not_searched_until_someone_searches_it(self):
        s = Session()
        oid = s.ready()
        added = s.ok("add_own_favourite", {"outing_id": oid, "member_id": "m2", "name": "A new band"},
                     s.organiser)
        fav = next(f for f in s.outing(oid)["members"][1]["favourites"] if f["id"] == added["favouriteId"])
        self.assertEqual((fav["searched"], fav["candidates"], fav["namedBy"]), (False, [], "organiser_for"))
        s.ok("look_up_favourite", {"outing_id": oid, "member_id": "m2", "favourite_id": added["favouriteId"]})
        fav = next(f for f in s.outing(oid)["members"][1]["favourites"] if f["id"] == added["favouriteId"])
        self.assertTrue(fav["searched"])
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "favourite_unresolved")


if __name__ == "__main__":
    unittest.main()
