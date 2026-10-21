"""Every state the plan's Design row promises has a screen: for each, the sentence the page shows for it is in
the page's script, and the state itself can be produced and read from the outing the page reads."""
import os
import unittest

from common_ground import sources, web
from tests.served import Browser, Served
from tests.session import (
    ScriptedSource, Session, Transport, forward, live_session, reverse, slice_of, verified,
)
from tests.test_comparison import three
from tests.test_outings import sample_args
from tests.test_searched_marks import Silent, sample_with


def script():
    with open(os.path.join(web.WEB_DIR, "app.js"), encoding="utf-8") as fh:
        return " ".join(fh.read().split())


def page_says(test, *sentences):
    text = script()
    for sentence in sentences:
        test.assertIn(sentence, text)


class WhatTheDesignRowPromises(unittest.TestCase):
    def test_no_key_synthetic_banner(self):
        page_says(self, "Synthetic sample data. Qloo is not being called.",
                  "No Qloo key is set on this server.")
        with Served() as served:
            browser = Browser(served)
            browser.open()
            mode = browser.state()["mode"]
        self.assertEqual((mode["source"], mode["key"]), ("fake", "missing"))

    def test_an_ambiguous_favourite_shows_candidates_and_is_never_guessed(self):
        page_says(self, "Which one did ${member.name} mean by", "Not matched yet. Choose the one meant")
        s = Session()
        oid = s.open()
        s.search_all(oid)
        favourite = s.outing(oid)["members"][0]["favourites"][0]
        self.assertGreater(len(favourite["candidates"]), 1)
        self.assertIsNone(favourite["resolved"])
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "needs_favourites")

    def test_a_favourite_qloo_cannot_find(self):
        page_says(self, "Qloo found nothing for “${favourite.name}”, so it is not used.")
        s = Session(Silent())
        oid = s.open(sample_with("Nothing Known"))
        search = {"outing_id": oid, "member_id": "m1", "favourite_id": "f1"}
        self.assertEqual(s.code("look_up_favourite", search), "qloo_no_results")
        found = s.outing(oid)["members"][0]["favourites"][0]
        self.assertEqual((found["searched"], found["candidates"]), (True, []))

    def test_a_person_with_nothing_resolved(self):
        page_says(self, "Waiting for ${listOf(waiting)} to say which match they meant.",
                  "Every person needs at least one resolved match before places can be compared.")
        s = Session()
        oid = s.open()
        s.search_all(oid)
        self.assertEqual(s.code("run_comparison", {"outing_id": oid}), "needs_favourites")

    def test_no_place_is_shared_by_everyone_and_the_closest_places_name_who_is_left_out(self):
        page_says(self, "No place is shared by everyone. The closest places below name who each one "
                        "leaves out.", "Closest places: each leaves someone out")
        opposed = {"fwd": forward, "rev": reverse, "mid": forward}
        s = Session(ScriptedSource(opposed, with_explainability=False))
        oid = s.ready(three("fwd", "rev", "mid"), kind=False)
        result = s.compare(oid)
        self.assertEqual(result["outcome"], "none_shared")
        self.assertTrue(result["near"] and all(p["leftOut"] for p in result["near"]))

    def test_no_place_comes_close_only_when_qloo_ranked_part_of_the_long_list(self):
        page_says(self, "No place comes close: ${who} ranked only part of the long list")
        partial = {"a": slice_of(0, 4), "b": slice_of(1, 4), "c": slice_of(2, 4)}
        s = Session(ScriptedSource(partial, group_size=12, with_explainability=False))
        oid = s.ready(three("a", "b", "c"), kind=False)
        s.compare(oid)
        self.assertEqual(s.compare(oid, complete=True)["outcome"], "none_close")

    def test_a_thin_long_list(self):
        page_says(self, "Too few places came back to compare people, so nothing was ranked.",
                  "returned, not ranked:")
        s = Session(ScriptedSource({}, group_size=4))
        oid = s.ready({"members": sample_args()["members"][:2]}, kind=False)
        self.assertEqual(s.compare(oid)["outcome"], "thin_list")

    def test_a_call_limit_reached_which_the_organiser_can_lift(self):
        page_says(self, "This outing has used all ${b.limit} of its Qloo calls. Only you can raise the limit",
                  "Raise the limit",
                  "This outing has used its Qloo call limit. Only the organiser can lift it.")
        s = Session()
        oid = s.ready(kind=False)
        self.assertEqual(s.compare(oid, max_calls=10)["stoppedBecause"], "over_limit")
        self.assertEqual(s.compare(oid, max_calls=9)["stoppedBecause"], "over_limit")
        s.ok("lift_call_limit", {"outing_id": oid, "limit": 40}, s.organiser)
        self.assertEqual(s.outing(oid)["budget"]["limit"], 40)

    def test_the_daily_ceiling_spent(self):
        page_says(self, "Daily ceiling spent: showing synthetic sample data.",
                  "Daily ceiling spent: live Qloo calls are refused for this outing")
        s = live_session(Transport(), ceiling=1, sample=sources.FakeSource())
        with verified():
            live = s.open()
            s.ok("look_up_favourite", {"outing_id": live, "member_id": "m1", "favourite_id": "f1"})
            self.assertEqual(s.outing(s.open())["source"], "synthetic")
            self.assertEqual(s.code("look_up_favourite", {"outing_id": live, "member_id": "m2",
                                                          "favourite_id": "f3"}), "daily_ceiling_spent")

    def test_the_agents_daily_allowance_spent(self):
        page_says(self, "The agent has used its Qloo calls for the day. A person's own click still runs.",
                  "It stopped at the agent's daily allowance.")

    def test_a_qloo_error(self):
        page_says(self, "Qloo could not be reached. Try again in a moment.",
                  "Qloo is limiting requests. Wait a moment and try again.",
                  "It stopped because Qloo refused requests.")
        transport = Transport(failures=[503] * 20)
        s = live_session(transport)
        with verified():
            oid = s.open()
            self.assertEqual(s.code("look_up_favourite", {"outing_id": oid, "member_id": "m1",
                                                          "favourite_id": "f1"}), "qloo_unavailable")

    def test_a_sleeping_free_host_wakes_empty(self):
        page_says(self, "This workspace is gone. The server restarted or woke from sleep")
        with Served() as before:
            browser = Browser(before)
            browser.open()
            cookie = browser.cookie
        with Served() as after:
            woken = Browser(after)
            woken.cookie = cookie
            reply = woken.get("/api/state")
        self.assertEqual((reply.status, reply.json["outcome"]), (401, "no_workspace"))

    def test_a_plain_http_page(self):
        page_says(self, "This page was loaded over plain HTTP, so your browser sends no label with its "
                        "requests", "A workspace cannot be kept over plain HTTP")
        with Served() as served:
            reply = served.call("GET", "/", headers={"Sec-Fetch-Site": "none"})
        self.assertEqual(reply.status, 200)

    def test_a_browser_that_sends_no_request_label(self):
        page_says(self, "Your browser does not label requests, so you cannot resolve a match or sign off "
                        "here.")
        with Served() as served:
            browser = Browser(served, labelled=False)
            browser.open()
            state = browser.state()
        self.assertEqual((state["actor"], state["actorWhy"]), ("agent", "no_fetch_metadata"))


class TextBoxesTakeEnter(unittest.TestCase):
    def test_every_box_beside_a_button_presses_it_on_enter(self):
        defined_once = 1
        self.assertEqual(script().count("enterPresses(") - defined_once, 4)


if __name__ == "__main__":
    unittest.main()
