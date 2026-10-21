import json
import unittest

from common_ground import agent_tools, outings, person_verbs
from common_ground.gateway import Actor
from tests.session import Session
from tests.test_outings import sample_args

VERBS = ("resolve_match", "add_own_favourite", "pick_place", "sign_off_message", "change_conditions",
         "rule_out_place", "lift_call_limit")
SOME_ARGS = {"outing_id": "out_001", "member_id": "m1", "favourite_id": "f1", "entity_id": "x", "name": "x",
             "place_id": "x", "revision": 1, "draft_id": "d1", "sender_name": "Noor", "reason": "x",
             "limit": 40, "day": "friday"}


def wanted(verb):
    return {k: v for k, v in SOME_ARGS.items() if k in person_verbs.VERBS[verb].args.declared}


class TheRegistryHoldsNoVerb(unittest.TestCase):
    def test_the_seven_verbs_are_exactly_the_human_ones_and_none_is_a_tool(self):
        self.assertEqual(sorted(person_verbs.VERBS), sorted(VERBS))
        self.assertFalse(set(VERBS) & set(agent_tools.TOOLS))
        self.assertFalse(set(VERBS) & {t["name"] for t in agent_tools.listing()})

    def test_the_tool_list_is_the_eight_tools_of_the_plan(self):
        self.assertEqual(sorted(agent_tools.TOOLS), sorted((
            "open_outing", "look_up_favourite", "look_up_kind", "run_comparison", "show_evidence",
            "write_draft", "read_outing", "spend_report",
        )))

    def test_no_tool_description_or_schema_names_a_verb(self):
        listing = json.dumps(agent_tools.listing())
        for verb in VERBS:
            self.assertNotIn(verb, listing)


class AnAgentIsRefusedEveryVerb(unittest.TestCase):
    def test_each_verb_is_not_a_tool_for_the_agent_even_with_good_arguments(self):
        s = Session()
        s.ready()
        before = s.outing()
        for verb in VERBS:
            with self.subTest(verb):
                self.assertEqual(s.code(verb, wanted(verb)), "not_a_tool")
        self.assertEqual(s.outing(), before)

    def test_an_unknown_name_is_not_a_tool_for_anyone(self):
        s = Session()
        for actor in (s.agent, s.organiser):
            for name in ("nope", "", "x" * 500, None, 5):
                with self.subTest(name=name, kind=actor.kind):
                    self.assertEqual(s.code(name, {}, actor), "not_a_tool")

    def test_refusals_are_logged_with_the_caller(self):
        s = Session()
        s.code("pick_place", wanted("pick_place"))
        s.ok("spend_report", {})
        log = s.gateway.document["workspaces"][0]["activityLog"]
        self.assertEqual([(e["actor"], e["as"], e["tool"], e["outcome"]) for e in log],
                         [("agent", None, "pick_place", "not_a_tool"), ("agent", None, "spend_report", "ok")])

    def test_the_log_keeps_no_arguments_and_cuts_a_long_name(self):
        s = Session()
        s.code("x" * 500, {"secret": "hunter2"})
        entry = s.gateway.document["workspaces"][0]["activityLog"][-1]
        self.assertEqual(len(entry["tool"]), 64)
        self.assertNotIn("hunter2", json.dumps(s.gateway.document["workspaces"][0]["activityLog"]))


class AMembersLink(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.oid = self.s.ready(kind=False)
        self.out = self.s.outing(self.oid)

    def link(self, member):
        return self.s.member_link(self.oid, member)

    def args(self, member, **extra):
        fav = next(m for m in self.out["members"] if m["id"] == member)["favourites"][0]
        return {"outing_id": self.oid, "member_id": member, "favourite_id": fav["id"],
                "entity_id": fav["candidates"][1]["entityId"], **extra}

    def test_runs_the_two_verbs_for_that_member_and_records_it_as_their_own(self):
        answer = self.s.ok("resolve_match", self.args("m2"), self.link("m2"))
        self.assertEqual(answer["resolvedBy"], "member")
        added = self.s.ok("add_own_favourite", {"outing_id": self.oid, "member_id": "m2", "name": "A band"},
                          self.link("m2"))
        self.assertEqual((added["namedBy"], added["favouriteId"]), ("member", "f9"))
        self.assertEqual(self.s.outing(self.oid)["members"][1]["favourites"][-1]["namedBy"], "member")

    def test_cannot_resolve_or_add_for_anyone_else(self):
        self.assertEqual(self.s.code("resolve_match", self.args("m3"), self.link("m2")), "wrong_member")
        self.assertEqual(self.s.code(
            "add_own_favourite", {"outing_id": self.oid, "member_id": "m3", "name": "x"}, self.link("m2")
        ), "wrong_member")

    def test_a_link_belongs_to_one_outing(self):
        other = self.s.open()
        self.assertNotEqual(other, self.oid)
        self.assertEqual(self.s.code(
            "resolve_match", {**self.args("m2"), "outing_id": other}, self.link("m2")
        ), "wrong_member")

    def test_runs_nothing_else(self):
        for name in VERBS[2:]:
            with self.subTest(name):
                self.assertEqual(self.s.code(name, wanted(name), self.link("m1")), "wrong_actor")
        for name in agent_tools.TOOLS:
            with self.subTest(name):
                self.assertEqual(self.s.code(name, {"outing_id": self.oid}, self.link("m1")), "wrong_actor")

    def test_the_log_names_the_member(self):
        self.s.code("pick_place", wanted("pick_place"), self.link("m4"))
        entry = self.s.gateway.document["workspaces"][0]["activityLog"][-1]
        self.assertEqual(
            (entry["actor"], entry["as"], entry["outcome"]), ("person", "member:m4", "wrong_actor")
        )

    def test_a_member_cannot_see_others_links_by_opening_an_outing(self):
        self.assertEqual(self.s.code("open_outing", {}, self.link("m1")), "wrong_actor")


class ProvenanceIsPartOfTheVerb(unittest.TestCase):
    def test_the_organisers_own_favourite_is_theirs_and_the_rest_are_on_behalf(self):
        s = Session()
        oid = s.ready()
        by = {m["id"]: {f["resolvedBy"] for f in m["favourites"]} for m in s.outing(oid)["members"]}
        self.assertEqual(by, {"m1": {"member"}, "m2": {"organiser_for"}, "m3": {"organiser_for"},
                              "m4": {"organiser_for"}})

    def test_the_organiser_adding_a_favourite_for_someone_is_recorded_so(self):
        s = Session()
        oid = s.open()
        own = s.ok("add_own_favourite", {"outing_id": oid, "member_id": "m1", "name": "Mine"}, s.organiser)
        theirs = {"outing_id": oid, "member_id": "m2", "name": "Theirs"}
        other = s.ok("add_own_favourite", theirs, s.organiser)
        self.assertEqual((own["namedBy"], other["namedBy"]), ("member", "organiser_for"))

    def test_a_fourth_favourite_is_refused(self):
        s = Session()
        oid = s.open()
        s.ok("add_own_favourite", {"outing_id": oid, "member_id": "m1", "name": "Third"}, s.organiser)
        self.assertEqual(s.code(
            "add_own_favourite", {"outing_id": oid, "member_id": "m1", "name": "Fourth"}, s.organiser
        ), "too_many_favourites")


class NamedRefusals(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.oid = self.s.ready()
        self.s.compare(self.oid)
        self.out = self.s.outing(self.oid)

    def place(self, status):
        return next(p for p in self.out["places"] if p["status"] == status)

    def pick(self, place_id, **extra):
        return {"outing_id": self.oid, "place_id": place_id, "revision": self.s.outing(self.oid)["revision"],
                **extra}

    def test_stale_revision(self):
        place = self.place("common")["entityId"]
        args = {**self.pick(place), "revision": 1}
        self.assertEqual(self.s.code("pick_place", args, self.s.organiser), "stale_revision")
        self.assertIsNone(self.s.outing(self.oid)["chosen"])

    def test_a_pick_of_a_common_place_needs_no_acknowledgement(self):
        answer = self.s.ok("pick_place", self.pick(self.place("common")["entityId"]), self.s.organiser)
        self.assertEqual(answer["leftOut"], [])
        self.assertEqual(self.s.outing(self.oid)["chosen"]["status"], "common")

    def test_a_near_place_needs_every_member_it_leaves_out_to_be_named(self):
        near = self.place("near")
        args = self.pick(near["entityId"])
        self.assertEqual(self.s.code("pick_place", args, self.s.organiser), "left_out_unacknowledged")
        args = self.pick(near["entityId"], acknowledge_left_out=near["leftOut"])
        answer = self.s.ok("pick_place", args, self.s.organiser)
        self.assertEqual(answer["leftOut"], near["leftOut"])
        self.assertEqual(self.s.outing(self.oid)["chosen"]["acknowledged"], near["leftOut"])

    def test_acknowledging_a_name_that_is_not_a_member_is_refused(self):
        args = self.pick(self.place("near")["entityId"], acknowledge_left_out=["m9"])
        self.assertEqual(self.s.code("pick_place", args, self.s.organiser), "unknown_member")

    def test_an_unknown_place(self):
        self.assertEqual(self.s.code("pick_place", self.pick("nope"), self.s.organiser), "unknown_place")

    def test_stale_comparison_after_a_condition_or_a_resolution_changes(self):
        place = self.place("common")["entityId"]
        self.s.ok("change_conditions", {"outing_id": self.oid, "price_max": 4}, self.s.organiser)
        self.assertEqual(self.s.code("pick_place", self.pick(place), self.s.organiser), "stale_comparison")
        self.assertEqual(self.s.code("write_draft", {
            "outing_id": self.oid, "place_id": place, "kind": "invitation"}), "stale_comparison")

    def test_a_resolution_also_makes_the_comparison_stale(self):
        fav = self.out["members"][1]["favourites"][0]
        self.s.ok("resolve_match", {
            "outing_id": self.oid, "member_id": "m2", "favourite_id": fav["id"],
            "entity_id": fav["candidates"][2]["entityId"],
        }, self.s.organiser)
        self.assertTrue(self.s.outing(self.oid)["comparison"]["stale"])

    def test_unknown_entity_and_unknown_tag(self):
        fav = self.out["members"][1]["favourites"][0]
        self.assertEqual(self.s.code("resolve_match", {
            "outing_id": self.oid, "member_id": "m2", "favourite_id": fav["id"], "entity_id": "not-offered",
        }, self.s.organiser), "unknown_entity")
        self.assertEqual(self.s.code("change_conditions", {
            "outing_id": self.oid, "kind_tag": "urn:tag:never-returned"}, self.s.organiser), "unknown_tag")

    def test_unknown_outing_member_and_favourite(self):
        self.assertEqual(self.s.code("read_outing", {"outing_id": "out_999"}), "unknown_outing")
        self.assertEqual(self.s.code("look_up_favourite", {
            "outing_id": self.oid, "member_id": "m9", "favourite_id": "f1"}), "unknown_member")
        self.assertEqual(self.s.code("look_up_favourite", {
            "outing_id": self.oid, "member_id": "m1", "favourite_id": "f99"}), "unknown_favourite")

    def test_smuggled_fields_are_refused_and_logged_not_dropped(self):
        place = self.place("common")["entityId"]
        self.assertEqual(self.s.code("write_draft", {
            "outing_id": self.oid, "place_id": place, "kind": "invitation", "status": "released"}),
            "smuggled_field")
        self.assertEqual(self.s.code("write_draft", {
            "outing_id": self.oid, "place_id": place, "kind": "invitation", "sender_name": "Noor"}),
            "smuggled_field")
        self.assertEqual(self.s.code("open_outing", {**sample_args(), "kind_tag": "x"}), "smuggled_field")
        self.assertEqual(
            self.s.code("run_comparison", {"outing_id": self.oid, "limit": 99}), "smuggled_field"
        )
        log = self.s.gateway.document["workspaces"][0]["activityLog"]
        self.assertEqual([e["outcome"] for e in log[-4:]], ["smuggled_field"] * 4)
        self.assertEqual(self.s.outing(self.oid)["drafts"], [])

    def test_bad_arguments(self):
        self.assertEqual(self.s.code("read_outing", {}), "bad_arguments")
        self.assertEqual(self.s.code("read_outing", {"outing_id": 5}), "bad_arguments")
        self.assertEqual(self.s.code("read_outing", ["out_001"]), "bad_arguments")
        self.assertEqual(self.s.code("pick_place", {**self.pick("x"), "revision": True}, self.s.organiser),
                         "bad_arguments")
        self.assertEqual(self.s.code("change_conditions", {"outing_id": self.oid}, self.s.organiser),
                         "bad_arguments")
        self.assertEqual(self.s.code("change_conditions", {"outing_id": self.oid, "day": "someday"},
                                     self.s.organiser), "bad_arguments")

    def test_no_arguments_at_all_is_fine_for_a_tool_that_takes_none(self):
        self.assertTrue(self.s.run("spend_report", None)["ok"])

    def test_unknown_actor_and_no_workspace(self):
        self.assertEqual(self.s.gateway.dispatch("spend_report", {}, "agent")["outcome"], "unknown_actor")
        self.assertEqual(self.s.gateway.dispatch("spend_report", {}, Actor("robot", self.s.ws))["outcome"],
                         "unknown_actor")
        self.assertEqual(self.s.gateway.dispatch("spend_report", {}, Actor.agent("ws_nope"))["outcome"],
                         "no_workspace")


class PickDraftSignOff(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.oid = self.s.ready()
        self.s.compare(self.oid)
        self.out = self.s.outing(self.oid)
        self.place = next(p for p in self.out["places"] if p["status"] == "common")["entityId"]

    def draft(self, kind="invitation"):
        return self.s.ok("write_draft", {"outing_id": self.oid, "place_id": self.place, "kind": kind})

    def revision(self):
        return self.s.outing(self.oid)["revision"]

    def test_a_draft_reads_draft_and_has_no_sender_until_signed_off(self):
        made = self.draft()
        self.assertTrue(made["text"].startswith("DRAFT. Not signed off. Do not send."))
        self.assertIn("[sender name needed]", made["text"])
        self.assertEqual(self.s.outing(self.oid)["drafts"][0]["state"], "draft")

    def test_only_a_person_signs_off_and_only_with_a_named_sender_and_a_fresh_revision(self):
        made = self.draft()
        args = {"outing_id": self.oid, "draft_id": made["draftId"], "revision": self.revision()}
        self.assertEqual(self.s.code("sign_off_message", {**args, "sender_name": "Noor"}), "not_a_tool")
        self.assertEqual(self.s.code("sign_off_message", args, self.s.organiser), "sender_missing")
        self.assertEqual(self.s.code("sign_off_message", {**args, "sender_name": "  "}, self.s.organiser),
                         "sender_missing")
        self.assertEqual(self.s.code("sign_off_message", {**args, "sender_name": "N", "revision": 1},
                                     self.s.organiser), "stale_revision")
        self.assertEqual(self.s.code("sign_off_message", {**args, "draft_id": "d9", "sender_name": "N"},
                                     self.s.organiser), "unknown_draft")
        done = self.s.ok("sign_off_message", {**args, "sender_name": "Noor"}, self.s.organiser)
        self.assertNotIn("DRAFT", done["text"])
        self.assertTrue(done["text"].rstrip().endswith("Noor"))
        again = {**args, "revision": self.revision(), "sender_name": "Other"}
        self.assertEqual(self.s.code("sign_off_message", again, self.s.organiser), "bad_arguments")

    def test_a_drafted_place_must_be_a_pick_or_the_chosen_place(self):
        other = next(p for p in self.out["places"] if p["status"] == "set_aside")["entityId"]
        args = {"outing_id": self.oid, "place_id": other, "kind": "invitation"}
        self.assertEqual(self.s.code("write_draft", args), "unknown_place")
        self.s.ok("pick_place", {
            "outing_id": self.oid, "place_id": other, "revision": self.revision(),
            "acknowledge_left_out": ["m1", "m2", "m3", "m4"],
        }, self.s.organiser)
        self.assertTrue(self.s.run("write_draft", args)["ok"])

    def test_both_kinds_are_drafted_and_a_third_is_not(self):
        self.assertIn("space for 4 people", self.draft("booking_request")["text"])
        self.assertEqual(self.s.code("write_draft", {
            "outing_id": self.oid, "place_id": self.place, "kind": "poem"}), "bad_arguments")

    def test_ruling_out_keeps_the_evidence_and_undo_restores_the_status(self):
        args = {"outing_id": self.oid, "place_id": self.place}
        self.assertEqual(self.s.code("rule_out_place", {**args, "reason": "x"}), "not_a_tool")
        self.assertEqual(self.s.code("rule_out_place", args, self.s.organiser), "bad_arguments")
        self.s.ok("rule_out_place", {**args, "reason": "Too loud"}, self.s.organiser)
        ruled = next(p for p in self.s.outing(self.oid)["places"] if p["entityId"] == self.place)
        self.assertEqual(
            (ruled["status"], ruled["ruledOut"]), ("ruled_out", {"reason": "Too loud", "was": "common"})
        )
        self.assertTrue(ruled["perMember"])
        self.assertEqual(self.s.code("pick_place", {**args, "revision": self.revision()}, self.s.organiser),
                         "unknown_place")
        self.s.ok("rule_out_place", {**args, "undo": True}, self.s.organiser)
        back = next(p for p in self.s.outing(self.oid)["places"] if p["entityId"] == self.place)
        self.assertEqual(back["status"], "common")
        self.assertNotIn("ruledOut", back)

    def test_ruling_out_the_chosen_place_clears_the_pick(self):
        self.s.ok("pick_place", {"outing_id": self.oid, "place_id": self.place, "revision": self.revision()},
                  self.s.organiser)
        self.s.ok("rule_out_place", {"outing_id": self.oid, "place_id": self.place, "reason": "Closed"},
                  self.s.organiser)
        self.assertIsNone(self.s.outing(self.oid)["chosen"])

    def test_a_ruling_survives_the_comparison_being_resumed(self):
        self.s.ok("rule_out_place", {"outing_id": self.oid, "place_id": self.place, "reason": "Too loud"},
                  self.s.organiser)
        self.s.compare(self.oid)
        kept = next(p for p in self.s.outing(self.oid)["places"] if p["entityId"] == self.place)
        self.assertEqual(kept["status"], "ruled_out")


class TheCallLimit(unittest.TestCase):
    def test_only_the_organiser_raises_it_and_only_up_to_sixty(self):
        s = Session()
        oid = s.open()
        self.assertEqual(s.code("lift_call_limit", {"outing_id": oid, "limit": 40}), "not_a_tool")
        self.assertEqual(s.ok("lift_call_limit", {"outing_id": oid, "limit": 40}, s.organiser)["limit"], 40)
        self.assertEqual(s.outing(oid)["budget"]["limit"], 40)
        for bad in (40, 30, 61, 1000):
            with self.subTest(bad):
                self.assertEqual(s.code("lift_call_limit", {"outing_id": oid, "limit": bad}, s.organiser),
                                 "bad_arguments")
        self.assertEqual(s.ok("lift_call_limit", {"outing_id": oid, "limit": 60}, s.organiser)["limit"], 60)

    def test_the_settings_choose_the_limit_a_new_outing_starts_with(self):
        s = Session(call_limit=12)
        self.assertEqual(s.outing(s.open())["budget"]["limit"], 12)


class WhatEachCallerIsGiven(unittest.TestCase):
    def test_an_agent_never_receives_a_member_link_and_the_organiser_does(self):
        s = Session()
        from_agent = s.ok("open_outing", sample_args())
        from_organiser = s.ok("open_outing", sample_args(), s.organiser)
        self.assertFalse(any("link" in m for m in from_agent["members"]))
        links = [m["link"] for m in from_organiser["members"]]
        tokens = [m["token"] for m in s.outing(from_organiser["outingId"])["members"]]
        self.assertEqual(links, ["/m/" + t for t in tokens])

    def test_read_outing_carries_no_token_for_anyone(self):
        s = Session()
        oid = s.ready()
        s.compare(oid)
        for actor in (s.agent, s.organiser):
            text = json.dumps(s.ok("read_outing", {"outing_id": oid}, actor))
            workspace = outings.workspace(s.gateway.document, s.ws)
            tokens = [m["token"] for m in s.outing(oid)["members"]] + [workspace["agentToken"]]
            for token in tokens:
                self.assertNotIn(token, text)

    def test_spend_report_is_the_same_numbers_for_everyone_and_never_the_key(self):
        s = Session(provider="fake")
        oid = s.ready()
        report = s.ok("spend_report", {})
        self.assertEqual(report["outings"][0], {
            "id": oid, "source": "synthetic", "spent": 9, "limit": 30, "left": 21, "saved": 0,
            "stoppedBecause": None})
        self.assertEqual((report["source"], report["key"]), ("fake", "missing"))


if __name__ == "__main__":
    unittest.main()
