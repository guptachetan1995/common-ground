import unittest

from common_ground import fair_share, measured, sources
from tests.session import (
    ScriptedSource, Session, Transport, first, forward, live_session, reverse, slice_of, verified,
)
from tests.test_outings import sample_args


def three(*favourites):
    names = ("Ada", "Bea", "Cy")
    return {
        "members": [{"name": n, "favourites": [f]} for n, f in zip(names, favourites)],
        "kind_query": None,
    }


def trace_of(session, outing="out_001"):
    return session.outing(outing)["trace"]


def calls(result):
    return result["callsSpent"]


class ScenarioA(unittest.TestCase):
    """The Friday Table: four people, two favourites each, a kind tag found, every ranking made."""

    @classmethod
    def setUpClass(cls):
        cls.s = Session()
        cls.oid = cls.s.ready()
        cls.before = cls.s.outing(cls.oid)["budget"]["spent"]
        cls.result = cls.s.compare(cls.oid)
        cls.out = cls.s.outing(cls.oid)

    def test_the_searches_the_tag_the_group_search_and_four_rankings_are_fourteen_of_thirty(self):
        self.assertEqual(self.before, 9)
        self.assertEqual((self.result["callsThisRun"], self.result["callsSpent"], self.result["callLimit"]),
                         (5, 14, 30))
        self.assertEqual(self.out["budget"], {"limit": 30, "spent": 14, "saved": 0, "stoppedBecause": "done"})
        tools = [e["tool"] for e in self.out["trace"] if e["request"]]
        self.assertEqual(tools, ["look_up_favourite"] * 8 + ["look_up_kind"] + ["run_comparison"] * 5)
        paths = [e["request"]["path"] for e in self.out["trace"] if e["request"]]
        self.assertEqual(paths, ["/search"] * 8 + ["/v2/tags"] + ["/v2/insights"] * 5)

    def test_every_call_and_every_stop_carries_its_reason_in_order(self):
        steps = [e["step"] for e in self.out["trace"]]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))
        self.assertTrue(all(e["because"] for e in self.out["trace"]))
        spent = [e["callsSpent"] for e in self.out["trace"]]
        self.assertEqual(spent, sorted(spent))
        self.assertEqual(self.out["trace"][-1]["request"], None)
        self.assertEqual(self.out["trace"][-1]["because"], "every member is ranked")
        self.assertEqual(self.result["trace"], self.out["trace"][-6:])

    def test_the_comparisons_own_calls_are_the_agents_even_when_a_person_clicks(self):
        self.assertEqual({e["actor"] for e in self.out["trace"] if e["tool"] == "run_comparison"}, {"agent"})
        self.assertEqual({e["actor"] for e in self.out["trace"] if e["tool"] == "look_up_kind"}, {"agent"})
        s = Session()
        oid = s.ready(actor=s.organiser)
        s.compare(oid, s.organiser)
        trace = s.outing(oid)["trace"]
        self.assertEqual({e["actor"] for e in trace if e["tool"] == "run_comparison"}, {"agent"})
        self.assertEqual({e["actor"] for e in trace if e["tool"] == "look_up_favourite"}, {"person"})
        self.assertEqual({r["startedBy"] for r in s.gateway.document["calls"]}, {"person"})

    def test_members_are_ranked_least_led_on_first(self):
        lean = self.out["longList"]["lean"]
        self.assertEqual(set(lean), {"m1", "m2", "m3", "m4"})
        ranked = [e["member"] for e in self.out["trace"] if e["tool"] == "run_comparison" and e["member"]]
        self.assertEqual(ranked, sorted(lean, key=lean.get))
        self.assertEqual(self.out["comparison"]["rankedMembers"], ranked)
        self.assertIn("led the group search least", self.out["trace"][-5]["because"])

    def test_the_long_list_is_ranked_for_everyone_and_the_statuses_follow_the_rule(self):
        places = self.out["places"]
        self.assertEqual(len(places), 50)
        self.assertEqual(self.out["longList"]["size"], 50)
        self.assertTrue(all(len(p["perMember"]) == 4 for p in places))
        self.assertEqual([m["member"] for m in places[0]["perMember"]], ["m1", "m2", "m3", "m4"])
        statuses = [p["status"] for p in places]
        self.assertEqual(statuses, sorted(statuses, key=["common", "near", "set_aside"].index))
        common = [p for p in places if p["status"] == "common"]
        self.assertEqual(self.out["comparison"]["foundCommon"], len(common))
        self.assertGreater(len(common), 0)
        self.assertLessEqual(statuses.count("near"), fair_share.NEAR_SHOWN)
        for place in common:
            self.assertTrue(all(pm["inUpperHalf"] for pm in place["perMember"]))
            self.assertEqual(place["leftOut"], [])
        worst = [max(pm["rank"] for pm in p["perMember"]) for p in common]
        self.assertEqual(worst, sorted(worst))
        for place in places:
            if place["status"] == "near":
                self.assertGreaterEqual(len(place["leftOut"]), 1)

    def test_each_figure_carries_whose_it_is_and_the_bar_comes_from_the_rank(self):
        entry = self.out["places"][0]["perMember"][0]
        self.assertEqual(set(entry), {"member", "rank", "bar", "affinity", "band", "inUpperHalf", "ranked",
                                      "because", "restsOnOrganiserResolution"})
        self.assertEqual(entry["bar"], round(fair_share.bar_length(entry["rank"], 50), 4))
        self.assertEqual(entry["band"], fair_share.band(entry["affinity"]))
        mine = {f["id"] for f in self.out["members"][0]["favourites"]}
        self.assertTrue(entry["because"])
        self.assertTrue({line["favourite"] for line in entry["because"]} <= mine)

    def test_only_the_organisers_own_favourites_are_not_marked_as_resolved_for_them(self):
        flags = {pm["member"]: pm["restsOnOrganiserResolution"] for pm in self.out["places"][0]["perMember"]}
        self.assertEqual(flags, {"m1": False, "m2": True, "m3": True, "m4": True})

    def test_the_effect_of_group_size_is_printed(self):
        self.assertEqual(self.out["comparison"]["expectedByChance"], 3.1)
        found = self.out["comparison"]["foundCommon"]
        self.assertEqual(self.result["chance"], f"unrelated rankings would share about 3.1 of 50; "
                                                f"this group shares {found}")

    def test_the_trace_prints_parameters_but_counts_long_id_lists_and_has_no_names(self):
        group, *rankings = [e for e in self.out["trace"] if e["tool"] == "run_comparison" and e["request"]]
        self.assertEqual(group["request"]["params"]["filter.type"], "urn:entity:place")
        self.assertEqual(group["request"]["params"]["filter.hours"], "friday")
        self.assertEqual(group["request"]["params"]["signal.interests.entities"], "<8 ids>")
        for entry in rankings:
            params = entry["request"]["params"]
            self.assertEqual(params["filter.results.entities"], "<50 ids>")
            self.assertEqual(len(params["signal.interests.entities"].split(",")), 2)
            self.assertEqual(params["filter.hours"], "friday")
        for entry in self.out["trace"]:
            if entry["request"]:
                self.assertNotIn("Noor", str(entry["request"]))

    def test_it_is_resumed_not_repeated(self):
        before = self.s.outing(self.oid)
        again = self.s.compare(self.oid)
        after = self.s.outing(self.oid)
        self.assertEqual((again["callsThisRun"], after["budget"]["spent"]), (0, 14))
        self.assertEqual(after["places"], before["places"])
        self.assertEqual(after["comparison"], before["comparison"])
        self.assertEqual(after["trace"][-1]["because"], "every member is ranked")


class ScenarioB(unittest.TestCase):
    """No common ground: the second ranking leaves nothing shared, so the third is not spent."""

    def setUp(self):
        script = {"fwd": forward, "rev": reverse, "mid": forward}
        self.s = Session(ScriptedSource(script, with_explainability=False))
        self.oid = self.s.ready(three("fwd", "rev", "mid"), kind=False)

    def test_it_stops_after_two_rankings_and_says_what_it_saved(self):
        result = self.s.compare(self.oid)
        self.assertEqual((result["callsThisRun"], result["callsSpent"]), (3, 6))
        self.assertEqual((result["stoppedBecause"], result["saved"], result["outcome"]),
                         ("no_common_ground", 1, "none_shared"))
        self.assertEqual(result["unranked"], ["Cy"])
        self.assertFalse(result["complete"])
        out = self.s.outing(self.oid)
        self.assertEqual(
            out["budget"], {"limit": 30, "spent": 6, "saved": 1, "stoppedBecause": "no_common_ground"}
        )
        self.assertIn("ranking for Cy was not spent", out["trace"][-1]["because"])
        self.assertEqual(out["comparison"]["unrankedMembers"], ["m3"])

    def test_the_closest_places_name_who_is_left_out_of_them(self):
        result = self.s.compare(self.oid)
        self.assertEqual(result["common"], [])
        self.assertEqual(len(result["near"]), fair_share.NEAR_SHOWN)
        for place in result["near"]:
            self.assertEqual(len(place["leftOut"]), 1)
            self.assertIn(place["leftOut"][0], ("Ada", "Bea"))

    def test_asking_again_without_complete_spends_nothing_more(self):
        self.s.compare(self.oid)
        again = self.s.compare(self.oid)
        self.assertEqual((again["callsThisRun"], again["stoppedBecause"], again["saved"]),
                         (0, "no_common_ground", 1))
        self.assertEqual(self.s.outing(self.oid)["budget"]["spent"], 6)

    def test_complete_spends_the_skipped_ranking_and_only_that(self):
        self.s.compare(self.oid)
        result = self.s.compare(self.oid, complete=True)
        self.assertEqual((result["callsThisRun"], result["callsSpent"], result["saved"]), (1, 7, 0))
        self.assertEqual(
            (result["stoppedBecause"], result["complete"], result["unranked"]), ("done", True, [])
        )
        out = self.s.outing(self.oid)
        self.assertEqual(out["comparison"]["rankedMembers"], ["m1", "m2", "m3"])
        self.assertTrue(all(len(p["perMember"]) == 3 for p in out["places"]))
        self.assertEqual(out["budget"]["saved"], 0)

    def test_asking_for_complete_from_the_start_never_stops_early(self):
        result = self.s.compare(self.oid, complete=True)
        self.assertEqual((result["callsSpent"], result["stoppedBecause"]), (7, "done"))

    def test_when_the_last_ranking_empties_the_common_set_it_is_done_not_saved(self):
        script = {"fwd": forward, "same": forward, "rev": reverse}
        s = Session(ScriptedSource(script, with_explainability=False))
        oid = s.ready(three("fwd", "same", "rev"), kind=False)
        result = s.compare(oid)
        self.assertEqual((result["stoppedBecause"], result["saved"], result["callsSpent"]), ("done", 0, 7))
        self.assertEqual((result["outcome"], s.outing(oid)["comparison"]["foundCommon"]), ("none_shared", 0))


class ScenarioC(unittest.TestCase):
    def setUp(self):
        self.s = Session(ScriptedSource({}, group_size=4))
        self.oid = self.s.ready({"members": sample_args()["members"][:2]}, kind=False)

    def test_a_thin_list_is_listed_unranked_and_no_ranking_is_spent(self):
        result = self.s.compare(self.oid)
        self.assertEqual((result["callsSpent"], result["stoppedBecause"], result["saved"], result["outcome"]),
                         (5, "thin_list", 2, "thin_list"))
        out = self.s.outing(self.oid)
        self.assertEqual(len(out["places"]), 4)
        self.assertTrue(all(p["perMember"] == [] and p["status"] == "set_aside" for p in out["places"]))
        self.assertEqual(out["comparison"]["rankedMembers"], [])
        self.assertFalse(out["comparison"]["complete"])
        self.assertIsNone(out["comparison"]["chance"])
        self.assertIn("fewer than the 10", out["trace"][-1]["because"])

    def test_asking_again_does_not_search_again(self):
        self.s.compare(self.oid)
        again = self.s.compare(self.oid)
        self.assertEqual((again["callsThisRun"], again["stoppedBecause"]), (0, "thin_list"))

    def test_no_places_at_all_is_a_thin_list_and_not_a_failure(self):
        s = Session(ScriptedSource({}, group_size=0))
        oid = s.ready({"members": sample_args()["members"][:2]}, kind=False)
        result = s.compare(oid)
        self.assertEqual((result["stoppedBecause"], result["outcome"]), ("thin_list", "thin_list"))
        self.assertEqual(s.outing(oid)["places"], [])
        self.assertEqual(s.outing(oid)["trace"][-2]["outcome"], "qloo_no_results")


class ScenarioD(unittest.TestCase):
    def setUp(self):
        self.s = Session(sources.FakeSource(with_explainability=False))
        self.oid = self.s.ready()
        self.result = self.s.compare(self.oid)
        self.out = self.s.outing(self.oid)

    def test_without_explainability_the_members_are_ranked_in_listed_order_with_no_because_lines(self):
        self.assertEqual(self.result["callsSpent"], 14)
        self.assertIsNone(self.out["longList"]["lean"])
        ranked = [e["member"] for e in self.out["trace"] if e["tool"] == "run_comparison" and e["member"]]
        self.assertEqual(ranked, ["m1", "m2", "m3", "m4"])
        self.assertTrue(all(pm["because"] == [] for p in self.out["places"] for pm in p["perMember"]))
        self.assertIn("listed order", self.out["trace"][-5]["because"])

    def test_the_ranks_and_picks_are_the_same_as_with_explainability(self):
        with_it = Session()
        oid = with_it.ready()
        with_it.compare(oid)
        ids = lambda o: [(p["entityId"], p["status"]) for p in o["places"]]  # noqa: E731
        self.assertEqual(sorted(ids(with_it.outing(oid))), sorted(ids(self.out)))

    def test_without_affinity_the_two_rank_tolerance_applies_and_the_run_still_works(self):
        s = Session(sources.FakeSource(with_affinity=False))
        oid = s.ready()
        result = s.compare(oid)
        self.assertEqual(result["callsSpent"], 14)
        entry = s.outing(oid)["places"][0]["perMember"][0]
        self.assertEqual((entry["affinity"], entry["band"]), (None, None))


class ScenarioE(unittest.TestCase):
    """Qloo ranks only part of the long list, so nothing comes close once everyone is ranked."""

    def setUp(self):
        script = {"a": slice_of(0, 4), "b": slice_of(1, 4), "c": slice_of(2, 4)}
        self.s = Session(ScriptedSource(script, group_size=12, with_explainability=False))
        self.oid = self.s.ready(three("a", "b", "c"), kind=False)

    def test_no_place_comes_close_only_when_rankings_are_partial(self):
        first_run = self.s.compare(self.oid)
        self.assertEqual((first_run["callsSpent"], first_run["stoppedBecause"]), (6, "no_common_ground"))
        self.assertTrue(first_run["near"])
        result = self.s.compare(self.oid, complete=True)
        self.assertEqual((result["callsSpent"], result["outcome"]), (7, "none_close"))
        self.assertEqual((result["common"], result["near"]), ([], []))
        out = self.s.outing(self.oid)
        self.assertEqual(out["comparison"]["partial"], {
            "m1": {"ranked": 4, "of": 12}, "m2": {"ranked": 4, "of": 12}, "m3": {"ranked": 4, "of": 12}})
        self.assertEqual(result["partialRankings"], {"Ada": {"ranked": 4, "of": 12},
                                                     "Bea": {"ranked": 4, "of": 12},
                                                     "Cy": {"ranked": 4, "of": 12}})
        self.assertTrue(all(p["status"] == "set_aside" for p in out["places"]))
        unranked_places = [pm for p in out["places"] for pm in p["perMember"] if not pm["ranked"]]
        self.assertEqual(len(unranked_places), 3 * 8)
        self.assertTrue(all(pm["rank"] is None and pm["bar"] == 0.0 for pm in unranked_places))
        notes = [e["because"] for e in out["trace"] if "ranked only" in e["because"]]
        self.assertEqual(len(notes), 3)
        self.assertIn("Qloo ranked only 4 of 12 places for Ada", notes[0])

    def test_eighty_per_cent_is_not_partial_and_just_below_it_is(self):
        for kept, partial in ((40, False), (39, True)):
            with self.subTest(kept=kept):
                s = Session(ScriptedSource({"a": first(kept), "b": first(kept), "c": first(kept)},
                                           with_explainability=False))
                oid = s.ready(three("a", "b", "c"), kind=False)
                s.compare(oid)
                self.assertEqual(bool(s.outing(oid)["comparison"]["partial"]), partial)

    def test_an_empty_ranking_is_not_a_failure_it_is_every_place_outside(self):
        s = Session(ScriptedSource({"a": forward, "b": first(0), "c": forward}, with_explainability=False))
        oid = s.ready(three("a", "b", "c"), kind=False)
        result = s.compare(oid, complete=True)
        self.assertEqual(result["stoppedBecause"], "done")
        self.assertEqual(s.outing(oid)["comparison"]["partial"]["m2"], {"ranked": 0, "of": 50})
        self.assertEqual(result["common"], [])


class TheStopRules(unittest.TestCase):
    def test_the_outings_call_limit_stops_a_comparison_and_lifting_it_resumes_it(self):
        s = Session(call_limit=11)
        oid = s.ready()
        result = s.compare(oid)
        self.assertEqual(
            (result["stoppedBecause"], result["callsSpent"], result["saved"]), ("over_limit", 11, 0)
        )
        self.assertEqual(len(result["unranked"]), 3)
        self.assertFalse(result["complete"])
        out = s.outing(oid)
        self.assertEqual(out["budget"]["stoppedBecause"], "over_limit")
        self.assertEqual(out["trace"][-2]["outcome"], "over_limit")
        self.assertIsNone(out["trace"][-2]["request"])
        s.ok("lift_call_limit", {"outing_id": oid, "limit": 30}, s.organiser)
        done = s.compare(oid)
        self.assertEqual((done["callsThisRun"], done["callsSpent"], done["stoppedBecause"]), (3, 14, "done"))
        self.assertTrue(done["complete"])

    def test_a_limit_spent_before_the_group_search_refuses_and_changes_nothing_else(self):
        s = Session(call_limit=9)
        oid = s.ready()
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "over_limit")
        out = s.outing(oid)
        self.assertIsNone(out["comparison"])
        self.assertEqual((out["budget"]["spent"], out["budget"]["stoppedBecause"]), (9, "over_limit"))

    def test_max_calls_can_only_lower_the_limit(self):
        s = Session()
        oid = s.ready()
        low = s.compare(oid, max_calls=10)
        self.assertEqual((low["callLimit"], low["callsSpent"], low["stoppedBecause"]), (10, 10, "over_limit"))
        high = s.compare(oid, max_calls=500)
        self.assertEqual((high["callLimit"], high["stoppedBecause"]), (30, "done"))
        self.assertEqual(s.code("run_comparison", {"outing_id": oid, "max_calls": -1}), "bad_arguments")

    def test_the_largest_outing_fits_the_default_limit_and_a_second_comparison_needs_it_lifted(self):
        names = [f"P{i}" for i in range(6)]
        members = [{"name": n, "favourites": [f"{n} one", f"{n} two", f"{n} three"]} for n in names]
        tastes = {f"{n} {w}".lower(): "forward" for n in names for w in ("one", "two", "three")}
        s = Session(sources.FakeSource(tastes=tastes))
        oid = s.ready({"members": members})
        first_run = s.compare(oid)
        self.assertEqual((first_run["callsSpent"], first_run["stoppedBecause"]), (26, "done"))
        s.ok("change_conditions", {"outing_id": oid, "price_max": 4}, s.organiser)
        second = s.compare(oid)
        self.assertEqual((second["callsSpent"], second["stoppedBecause"]), (30, "over_limit"))
        s.ok("lift_call_limit", {"outing_id": oid, "limit": 33}, s.organiser)
        third = s.compare(oid)
        self.assertEqual(
            (third["callsSpent"], third["stoppedBecause"], third["complete"]), (33, "done", True)
        )

    def test_what_a_comparison_needs(self):
        s = Session()
        oid = s.open()
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "needs_favourites")
        s.search_all(oid)
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "needs_favourites")
        s.resolve_all(oid)
        s.ok("add_own_favourite", {"outing_id": oid, "member_id": "m2", "name": "One more"}, s.organiser)
        s.ok("look_up_favourite", {"outing_id": oid, "member_id": "m2", "favourite_id": "f9"})
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "favourite_unresolved")
        self.assertEqual(s.outing(oid)["budget"]["spent"], 9)

    def test_a_favourite_nobody_searched_does_not_block_and_is_not_used(self):
        s = Session()
        oid = s.ready()
        s.ok("add_own_favourite", {"outing_id": oid, "member_id": "m3", "name": "Unsearched"}, s.organiser)
        self.assertEqual(s.compare(oid)["stoppedBecause"], "done")


class TheAllowanceAndTheCeiling(unittest.TestCase):
    def test_the_agent_allowance_stops_an_agent_started_comparison_across_outings(self):
        with verified():
            s = live_session(Transport(), agent_calls_per_day=3)
            oid = s.ready(actor=s.organiser)
            result = s.compare(oid)
            self.assertEqual((result["stoppedBecause"], result["callsThisRun"]), ("agent_allowance_spent", 3))
            self.assertEqual(len(result["unranked"]), 2)
            self.assertEqual(s.ok("spend_report", {})["agentCalls24h"], 3)
            other = s.ready({"day": "saturday"}, actor=s.organiser)
            self.assertEqual(s.code("run_comparison", {"outing_id": other}), "agent_allowance_spent")
            self.assertEqual(s.outing(other)["budget"]["stoppedBecause"], "agent_allowance_spent")

    def test_a_person_started_comparison_is_not_held_by_the_agents_allowance(self):
        with verified():
            s = live_session(Transport(), agent_calls_per_day=3)
            oid = s.ready(actor=s.organiser)
            result = s.compare(oid, actor=s.organiser)
            self.assertEqual((result["stoppedBecause"], result["callsSpent"]), ("done", 14))
            self.assertEqual(s.ok("spend_report", {})["agentCalls24h"], 0)

    def test_the_allowance_rolls_over_after_twenty_four_hours(self):
        with verified():
            s = live_session(Transport(), agent_calls_per_day=3)
            oid = s.ready(actor=s.organiser)
            s.compare(oid)
            s.clock.now += 86400 + 1
            self.assertEqual(s.ok("spend_report", {})["agentCalls24h"], 0)
            self.assertEqual(s.compare(oid)["stoppedBecause"], "done")

    def test_the_servers_daily_ceiling_stops_everyone(self):
        with verified():
            s = live_session(Transport(), ceiling=12)
            oid = s.ready(actor=s.organiser)
            result = s.compare(oid, actor=s.organiser)
            self.assertEqual((result["stoppedBecause"], result["callsSpent"]), ("daily_ceiling_spent", 12))
            self.assertEqual(s.code("look_up_kind", {"outing_id": oid, "query": "bar"}, s.organiser),
                             "daily_ceiling_spent")
            report = s.ok("spend_report", {})
            self.assertEqual((report["serverCallsToday"], report["serverCeiling"]), (12, 12))

    def test_repeated_requests_come_from_the_cache_and_cost_nothing(self):
        with verified():
            transport = Transport()
            s = live_session(transport)
            oid = s.ready(actor=s.organiser)
            s.compare(oid, actor=s.organiser)
            seen = len(transport.seen)
            s.ok("change_conditions", {"outing_id": oid, "price_max": 4}, s.organiser)
            s.ok("change_conditions", {"outing_id": oid, "price_max": 3}, s.organiser)
            again = s.compare(oid, actor=s.organiser)
            self.assertEqual(len(transport.seen), seen)
            self.assertEqual((again["callsThisRun"], again["callsSpent"]), (0, 14))
            rows = s.gateway.document["calls"]
            self.assertEqual([r["cache"] for r in rows[-5:]], ["cache"] * 5)
            self.assertEqual(s.ok("spend_report", {})["cacheHits"], 5)

    def test_a_synthetic_comparison_never_touches_the_agent_allowance_or_the_ceiling(self):
        s = Session(agent_calls_per_day=1)
        oid = s.ready()
        self.assertEqual(s.compare(oid)["stoppedBecause"], "done")
        report = s.ok("spend_report", {})
        self.assertEqual((report["agentCalls24h"], report["serverCallsToday"]), (0, 0))
        self.assertEqual({r["cache"] for r in s.gateway.document["calls"]}, {"synthetic"})


class WhenQlooRefuses(unittest.TestCase):
    @staticmethod
    def is_a_ranking(request):
        return "filter.results.entities" in request.as_dict()

    def test_two_rankings_in_a_row_refused_after_retries_stop_the_run_and_never_fall_back(self):
        with verified():
            s = live_session(Transport(fail_when=self.is_a_ranking))
            oid = s.ready(actor=s.organiser)
            result = s.compare(oid, actor=s.organiser)
            self.assertEqual(result["stoppedBecause"], "qloo_refused")
            self.assertEqual(result["callsThisRun"], 1 + 3 + 3)
            self.assertEqual(len(result["unranked"]), 4)
            self.assertEqual(s.clock.slept, [1.0, 3.0, 1.0, 3.0])
            out = s.outing(oid)
            self.assertEqual(out["comparison"]["rankedMembers"], [])
            self.assertTrue(all(p["perMember"] == [] for p in out["places"]))
            self.assertEqual({r["cache"] for r in s.gateway.document["calls"][-7:]}, {"miss"})

    def test_one_refused_ranking_leaves_that_person_unranked_and_the_next_run_asks_only_for_them(self):
        with verified():
            transport = Transport()
            s = live_session(transport)
            oid = s.ready(actor=s.organiser)
            refusals = {"left": 3}

            def the_first_ranking_only(request):
                if self.is_a_ranking(request) and refusals["left"]:
                    refusals["left"] -= 1
                    return True
                return False

            transport.fail_when = the_first_ranking_only
            result = s.compare(oid, actor=s.organiser)
            self.assertEqual(result["stoppedBecause"], "qloo_refused")
            self.assertEqual(len(result["unranked"]), 1)
            self.assertFalse(result["complete"])
            self.assertEqual(result["callsThisRun"], 1 + 3 + 3)
            self.assertEqual(len(s.outing(oid)["comparison"]["rankedMembers"]), 3)
            transport.fail_when = None
            resumed = s.compare(oid, actor=s.organiser)
            self.assertEqual((resumed["callsThisRun"], resumed["stoppedBecause"], resumed["complete"]),
                             (1, "done", True))

    def test_an_error_that_is_not_a_hiccup_is_raised_after_what_was_learned_is_kept(self):
        with verified():
            transport = Transport()
            s = live_session(transport)
            oid = s.ready(actor=s.organiser)
            transport.failures = [None, None, 401]
            answer = s.run("run_comparison", {"outing_id": oid}, s.organiser)
            self.assertEqual((answer["outcome"], answer["error"]["status"]), ("qloo_auth", 401))
            out = s.outing(oid)
            self.assertEqual(len(out["comparison"]["rankedMembers"]), 1)
            self.assertEqual((out["budget"]["stoppedBecause"], out["budget"]["spent"]), ("qloo_auth", 12))
            self.assertEqual(out["trace"][-1]["outcome"], "qloo_auth")


class Evidence(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.oid = self.s.ready()
        self.s.compare(self.oid)
        self.out = self.s.outing(self.oid)

    def test_evidence_is_the_stored_figures_with_names_and_the_rule(self):
        place = self.out["places"][0]
        before = self.out["budget"]["spent"]
        shown = self.s.ok("show_evidence", {"outing_id": self.oid, "place_id": place["entityId"]})
        self.assertEqual(self.s.outing(self.oid)["budget"]["spent"], before)
        self.assertEqual((shown["name"], shown["status"], shown["placedBy"]),
                         (place["name"], "common", place["placedBy"]))
        self.assertIn("upper half of every ranked person's own ranking", shown["rule"])
        self.assertEqual([m["name"] for m in shown["members"]], ["Noor", "Owen", "Pia", "Quinn"])
        self.assertEqual(shown["members"][1]["restsOnOrganiserResolution"], True)
        self.assertTrue(all(b["name"] for m in shown["members"] for b in m["because"]))

    def test_a_near_place_names_who_it_leaves_out(self):
        near = next(p for p in self.out["places"] if p["status"] == "near")
        shown = self.s.ok("show_evidence", {"outing_id": self.oid, "place_id": near["entityId"]})
        self.assertEqual(len(shown["leftOut"]), len(near["leftOut"]))
        self.assertTrue(shown["rule"].startswith("near"))

    def test_an_unknown_place_and_an_outing_never_compared(self):
        self.assertEqual(self.s.code("show_evidence", {"outing_id": self.oid, "place_id": "nope"}),
                         "unknown_place")
        other = self.s.open()
        self.assertEqual(
            self.s.code("show_evidence", {"outing_id": other, "place_id": "nope"}), "unknown_place"
        )


class TheMeasuredConstantsAreNotRedefined(unittest.TestCase):
    def test_the_long_list_asked_for_is_the_measured_one(self):
        s = Session()
        oid = s.ready()
        s.compare(oid)
        self.assertEqual(s.outing(oid)["longList"]["size"], measured.LONG_LIST)


if __name__ == "__main__":
    unittest.main()
