"""The day's live calls are spent: a new outing runs on invented sample data and says so, an outing opened
live stops with a named reason and is never switched, and the command line has no fallback."""
import unittest

from common_ground import outings, sources
from tests.served import Browser, Served
from tests.session import Session, Transport, live_session, verified
from tests.support import Stub, fake_key
from tests.test_command_line import SCENARIO, run
from tests.test_outings import sample_args

SPENT_BY_FOUR_SEARCHES_AND_A_KIND = 5


def spent(ceiling=SPENT_BY_FOUR_SEARCHES_AND_A_KIND):
    """A live session with a sample source, over a stand-in network, with a small ceiling for the day."""
    transport = Transport()
    return live_session(transport, ceiling=ceiling, sample=sources.FakeSource()), transport


class AnOutingKeepsTheSourceItOpenedOn(unittest.TestCase):
    def setUp(self):
        patch = verified()
        patch.__enter__()
        self.addCleanup(patch.__exit__, None, None, None)

    def live_outing_that_spends_the_day(self):
        s, transport = spent()
        live = s.open()
        for member in s.outing(live)["members"][:2]:
            for favourite in member["favourites"]:
                s.ok("look_up_favourite", {"outing_id": live, "member_id": member["id"],
                                           "favourite_id": favourite["id"]})
        s.ok("look_up_kind", {"outing_id": live, "query": "restaurant"})
        self.assertTrue(s.source.exhausted())
        return s, transport, live

    def test_before_the_ceiling_is_spent_a_new_outing_is_live(self):
        s, _ = spent()
        self.assertEqual(s.outing(s.open())["source"], "live")
        self.assertEqual(s.gateway.new_outing_source(), "live")

    def test_after_it_a_new_outing_runs_the_whole_walk_on_sample_data_and_costs_no_live_call(self):
        s, transport, _ = self.live_outing_that_spends_the_day()
        asked = len(transport.seen)
        self.assertEqual(s.gateway.new_outing_source(), "synthetic")
        sample = s.open()
        self.assertEqual(s.outing(sample)["source"], "synthetic")
        s.search_all(sample)
        s.resolve_all(sample)
        s.choose_kind(sample)
        result = s.compare(sample)
        self.assertEqual((result["callsSpent"], result["outcome"]), (14, "common"))
        self.assertEqual(len(transport.seen), asked)
        rows = s.gateway.document["calls"][SPENT_BY_FOUR_SEARCHES_AND_A_KIND:]
        self.assertEqual({row["cache"] for row in rows}, {"synthetic"})
        self.assertEqual(s.ok("spend_report", {})["serverCallsToday"], SPENT_BY_FOUR_SEARCHES_AND_A_KIND)

    def test_the_agent_is_told_which_source_it_got(self):
        s, _, _ = self.live_outing_that_spends_the_day()
        self.assertEqual(s.ok("open_outing", sample_args())["source"], "synthetic")

    def test_a_live_outing_stops_with_a_named_reason_and_is_never_switched(self):
        s, transport, live = self.live_outing_that_spends_the_day()
        asked, before = len(transport.seen), s.outing(live)
        member = before["members"][2]
        favourite = member["favourites"][0]
        refused = s.run("look_up_favourite", {"outing_id": live, "member_id": member["id"],
                                              "favourite_id": favourite["id"]})
        self.assertEqual((refused["ok"], refused["outcome"]), (False, "daily_ceiling_spent"))
        after = s.outing(live)
        self.assertEqual(after["source"], "live")
        self.assertEqual(after["members"][2]["favourites"][0]["candidates"], [])
        self.assertEqual(len(transport.seen), asked)
        self.assertNotIn("synthetic", {row["cache"] for row in s.gateway.document["calls"]})
        self.assertIs(s.gateway.source_for(after), s.source)

    def test_a_comparison_on_a_live_outing_stops_at_the_ceiling_and_keeps_its_source(self):
        s, transport = spent(ceiling=12)
        live = s.ready()
        self.assertEqual(s.outing(live)["source"], "live")
        self.assertEqual(s.ok("spend_report", {})["serverCallsToday"], 9)
        result = s.compare(live)
        self.assertEqual(result["stoppedBecause"], "daily_ceiling_spent")
        self.assertEqual(s.outing(live)["source"], "live")
        self.assertNotIn("synthetic", {row["cache"] for row in s.gateway.document["calls"]})

    def test_a_sample_outing_does_not_change_when_the_day_rolls_over(self):
        s, transport, _ = self.live_outing_that_spends_the_day()
        sample = s.open()
        s.clock.now += 2 * 86400
        self.assertFalse(s.source.exhausted())
        self.assertEqual(s.gateway.new_outing_source(), "live")
        self.assertEqual(s.outing(sample)["source"], "synthetic")
        asked = len(transport.seen)
        s.search_all(sample)
        self.assertEqual(len(transport.seen), asked)
        self.assertEqual(s.outing(s.open())["source"], "live")

    def test_an_outing_is_a_member_of_one_source_in_every_view(self):
        s, _, live = self.live_outing_that_spends_the_day()
        sample = s.open()
        self.assertEqual(outings.token_free(s.outing(sample))["source"], "synthetic")
        self.assertEqual(outings.token_free(s.outing(live))["source"], "live")
        by_outing = {o["id"]: o["source"] for o in s.ok("spend_report", {})["outings"]}
        self.assertEqual(by_outing, {live: "live", sample: "synthetic"})

    def test_without_a_sample_source_nothing_falls_back(self):
        transport = Transport()
        s = live_session(transport, ceiling=SPENT_BY_FOUR_SEARCHES_AND_A_KIND)
        self.assertIsNone(s.gateway.sample)
        first = s.open()
        for member in s.outing(first)["members"][:2]:
            for favourite in member["favourites"]:
                s.ok("look_up_favourite", {"outing_id": first, "member_id": member["id"],
                                           "favourite_id": favourite["id"]})
        s.ok("look_up_kind", {"outing_id": first, "query": "restaurant"})
        self.assertEqual(s.gateway.new_outing_source(), "live")
        unheard_of = [{"name": "Ana", "favourites": ["Zebra Zone"]}, {"name": "Bo", "favourites": ["Yak"]}]
        second = s.open({"members": unheard_of})
        self.assertEqual(s.outing(second)["source"], "live")
        member = s.outing(second)["members"][0]
        self.assertEqual(s.code("look_up_favourite", {"outing_id": second, "member_id": member["id"],
                                                      "favourite_id": member["favourites"][0]["id"]}),
                         "daily_ceiling_spent")

    def test_a_server_on_sample_data_has_no_second_source_to_hold(self):
        on_sample = Session(sample=sources.FakeSource())
        self.assertIsNone(on_sample.gateway.sample)
        self.assertEqual(on_sample.gateway.new_outing_source(), "synthetic")
        on_live = live_session(Transport(), sample=sources.FakeSource())
        self.assertIsNotNone(on_live.gateway.sample)


class TheCommandLineHasNoFallback(unittest.TestCase):
    def test_the_walk_stops_at_the_ceiling_and_the_stand_in_sees_only_live_requests(self):
        key = fake_key()
        with Stub(sources.FakeSource(), key) as stub, verified():
            code, out, err = run("plan", SCENARIO, "--provider", "live", "--base-url", stub.url,
                                 environ={"QLOO_API_KEY": key, "COMMON_GROUND_DAILY_LIVE_CALLS": "5"})
        self.assertEqual(code, 1)
        self.assertIn("refused (daily_ceiling_spent)", out)
        self.assertIn("stopped: refused (daily_ceiling_spent)", err)
        self.assertEqual(len(stub.requests), 5)
        self.assertNotIn("Synthetic sample data", out)
        self.assertNotIn(" synthetic", out)
        self.assertNotIn(key, out + err)


class TheServedPageIsToldWhichSourceEachOutingHas(unittest.TestCase):
    def test_state_and_member_view_carry_the_mode_and_the_source(self):
        s, _ = spent()
        with verified(), Served(session=s) as served:
            browser = Browser(served)
            browser.open()
            args = browser.get("/api/sample").json["args"]
            live = browser.ok("open_outing", args)
            self.assertEqual(live["source"], "live")
            mode = browser.state()["mode"]
            self.assertEqual((mode["source"], mode["ceilingSpent"], mode["newOutingsSynthetic"]),
                             ("live", False, False))
            for member in browser.state()["outings"][-1]["members"][:2]:
                for favourite in member["favourites"]:
                    browser.ok("look_up_favourite", {"outing_id": live["outingId"], "member_id": member["id"],
                                                     "favourite_id": favourite["id"]})
            browser.ok("look_up_kind", {"outing_id": live["outingId"], "query": "restaurant"})
            mode = browser.state()["mode"]
            self.assertEqual((mode["source"], mode["ceilingSpent"], mode["newOutingsSynthetic"]),
                             ("live", True, True))
            sample = browser.ok("open_outing", args)
            self.assertEqual(sample["source"], "synthetic")
            state = browser.state()
            self.assertEqual([o["source"] for o in state["outings"]], ["live", "synthetic"])
            token = state["memberLinks"][sample["outingId"]]["m2"].rsplit("/", 1)[1]
            member = browser.get(f"/api/member/{token}/state").json
            self.assertEqual(member["outing"]["source"], "synthetic")
            self.assertEqual(member["mode"]["source"], "live")
            self.assertIn("searched", member["member"]["favourites"][0])


if __name__ == "__main__":
    unittest.main()
