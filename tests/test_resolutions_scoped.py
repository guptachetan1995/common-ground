import unittest

from common_ground.gateway import Actor
from tests.session import Session, Transport, live_session, verified
from tests.test_outings import sample_args


def resolved(outing):
    return [(m["id"], f["id"], f["resolved"], f["resolvedBy"]) for m in outing["members"]
            for f in m["favourites"]]


def candidate_ids(outing):
    return [[c["entityId"] for c in f["candidates"]] for m in outing["members"] for f in m["favourites"]]


class AResolutionBelongsToOneOutingOnly(unittest.TestCase):
    def test_the_same_names_in_a_second_outing_come_back_unresolved_with_fresh_candidates(self):
        s = Session()
        first = s.ready()
        second = s.open()
        s.search_all(second)
        a, b = s.outing(first), s.outing(second)
        self.assertTrue(all(r[2] for r in resolved(a)))
        self.assertEqual([r[2:] for r in resolved(b)], [(None, None)] * 8)
        self.assertEqual(candidate_ids(a), candidate_ids(b))
        self.assertTrue(all(len(c) == 5 for c in candidate_ids(b)))

    def test_it_holds_when_the_second_search_is_a_cache_hit(self):
        with verified():
            s = live_session(Transport())
            first = s.ready(actor=s.organiser)
            before = len(s.gateway.document["calls"])
            second = s.open(actor=s.organiser)
            s.search_all(second, s.organiser)
            rows = s.gateway.document["calls"][before:]
            self.assertEqual([r["cache"] for r in rows], ["cache"] * 8)
            self.assertEqual([r[2:] for r in resolved(s.outing(second))], [(None, None)] * 8)
            self.assertTrue(all(r[2] for r in resolved(s.outing(first))))
            self.assertEqual(s.outing(second)["budget"]["spent"], 0)

    def test_a_comparison_in_the_second_outing_refuses_until_its_own_people_resolve(self):
        s = Session()
        s.ready()
        second = s.open()
        s.search_all(second)
        self.assertEqual(s.code("run_comparison", {"outing_id": second}), "needs_favourites")
        self.assertEqual(s.outing(second)["budget"]["spent"], 8)

    def test_resolving_in_one_outing_changes_nothing_in_another(self):
        s = Session()
        first = s.ready()
        second = s.open()
        s.search_all(second)
        frozen = s.outing(first)
        fav = s.outing(second)["members"][1]["favourites"][0]
        s.ok("resolve_match", {
            "outing_id": second, "member_id": "m2", "favourite_id": fav["id"],
            "entity_id": fav["candidates"][3]["entityId"],
        }, s.organiser)
        self.assertEqual(s.outing(first), frozen)

    def test_an_entity_offered_in_one_outing_is_not_accepted_in_another_unless_that_one_offered_it(self):
        s = Session()
        first = s.ready()
        second = s.open()
        entity = s.outing(first)["members"][0]["favourites"][0]["resolved"]
        self.assertEqual(s.code("resolve_match", {
            "outing_id": second, "member_id": "m1", "favourite_id": "f1", "entity_id": entity,
        }, s.organiser), "unknown_entity")

    def test_a_new_search_clears_the_outings_own_resolution(self):
        s = Session()
        oid = s.ready()
        self.assertTrue(s.outing(oid)["members"][0]["favourites"][0]["resolved"])
        s.ok("look_up_favourite", {"outing_id": oid, "member_id": "m1", "favourite_id": "f1"})
        out = s.outing(oid)
        self.assertEqual(out["members"][0]["favourites"][0]["resolved"], None)
        self.assertTrue(out["comparison"] is None)

    def test_a_workspace_never_sees_anothers_outings(self):
        s = Session()
        s.ready()
        other = s.gateway.new_workspace()
        answer = s.gateway.dispatch("read_outing", {"outing_id": "out_001"}, Actor.agent(other))
        self.assertEqual(answer["outcome"], "unknown_outing")


class OpeningAnOutingCannotRelaxAnything(unittest.TestCase):
    def test_a_looser_outing_starts_with_nothing_resolved_so_it_cannot_produce_agreement(self):
        s = Session()
        first = s.ready()
        s.compare(first)
        looser = s.ok("open_outing", {
            **sample_args(), "day": "saturday", "price_min": 1, "price_max": 4, "place_text": "Los Angeles",
        })["outingId"]
        self.assertEqual(s.code("run_comparison", {"outing_id": looser}), "needs_favourites")
        self.assertEqual(s.outing(looser)["conditions"]["kindTag"], None)
        self.assertEqual(s.outing(looser)["comparison"], None)

    def test_the_first_outings_conditions_and_comparison_are_untouched(self):
        s = Session()
        first = s.ready()
        s.compare(first)
        before = s.outing(first)
        s.ok("open_outing", {**sample_args(), "day": "sunday"})
        self.assertEqual(s.outing(first), before)

    def test_open_outing_takes_no_tag_resolution_or_status_field(self):
        s = Session()
        for field in ("kind_tag", "conditions", "resolved", "status", "chosen", "comparison", "limit",
                      "call_limit", "revision"):
            with self.subTest(field):
                self.assertEqual(s.code("open_outing", {**sample_args(), field: 1}), "smuggled_field")

    def test_the_kind_is_never_set_at_opening_only_by_the_organiser_afterwards(self):
        s = Session()
        oid = s.open({"kind_query": "restaurant"})
        self.assertIsNone(s.outing(oid)["conditions"]["kindTag"])
        self.assertEqual(s.outing(oid)["knownTags"], [])
        asked = {"outing_id": oid, "kind_tag": "x"}
        self.assertEqual(s.code("change_conditions", asked, s.agent), "not_a_tool")

    def test_the_agent_cannot_change_a_condition_of_an_open_outing(self):
        s = Session()
        oid = s.ready()
        before = s.outing(oid)["conditions"]
        for changes in ({"day": "sunday"}, {"price_max": 4}, {"place_text": "Elsewhere"}, {"radius_m": 5}):
            with self.subTest(changes):
                self.assertEqual(s.code("change_conditions", {"outing_id": oid, **changes}), "not_a_tool")
        self.assertEqual(s.outing(oid)["conditions"], before)


if __name__ == "__main__":
    unittest.main()
