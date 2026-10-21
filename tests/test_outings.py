import copy
import itertools
import json
import os
import unittest

from common_ground import outings, records
from common_ground.refusal import Refusal

SCENARIOS = os.path.join(os.path.dirname(__file__), "..", "scenarios")


def counter():
    numbers = itertools.count(1)
    return lambda: f"tok{next(numbers):028x}"


def sample_args():
    with open(os.path.join(SCENARIOS, "friday-table.json"), encoding="utf-8") as fh:
        return outings.scenario_args(json.load(fh))


def candidates(*names):
    return [records.Candidate(f"cand-{n}", n, "urn:entity:movie", 0.5, None) for n in names]


def refused(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except Refusal as error:
        return error.code, error.detail
    raise AssertionError("no refusal")


class Base(unittest.TestCase):
    def setUp(self):
        self.token = counter()
        self.doc, self.ws = outings.add_workspace(outings.new_doc(), token=self.token, now=1000.0)
        self.doc, self.out = outings.open_outing(
            self.doc, self.ws, sample_args(), token=self.token, now=1000.0
        )

    def outing(self):
        return outings.outing(self.doc, self.ws, self.out)

    def code(self, change, *args, **kwargs):
        """The refusal code of an outing function that takes the document, workspace and outing first."""
        return refused(change, self.doc, self.ws, self.out, *args, **kwargs)[0]

    def search_all(self):
        for m in self.outing()["members"]:
            for f in m["favourites"]:
                found = candidates(f"{f['id']}-a", f"{f['id']}-b")
                self.doc = outings.store_candidates(self.doc, self.ws, self.out, m["id"], f["id"], found)

    def stale_marker(self):
        self.doc = outings.update_outing(
            self.doc, self.ws, self.out, lambda o: o.update(comparison={"stale": False})
        )


class Workspaces(unittest.TestCase):
    def test_a_workspace_has_two_random_tokens_and_nothing_else_yet(self):
        token = counter()
        doc, ws_id = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
        ws = outings.workspace(doc, ws_id)
        self.assertNotEqual(ws["id"], "ws_" + ws["agentToken"])
        self.assertEqual((ws["outings"], ws["activityLog"], ws["agentCalls"]), ([], [], []))
        self.assertEqual(ws["createdAt"], "1970-01-01T00:00:00Z")
        self.assertEqual(outings.find_by_agent_token(doc, ws["agentToken"])["id"], ws_id)
        self.assertIsNone(outings.find_by_agent_token(doc, "nope"))

    def test_the_input_document_is_never_changed(self):
        token = counter()
        doc, ws_id = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
        frozen = copy.deepcopy(doc)
        outings.open_outing(doc, ws_id, sample_args(), token=token, now=1.0)
        outings.touch(doc, ws_id, 5.0)
        outings.record_agent_call(doc, ws_id, 5.0)
        outings.log_activity(doc, ws_id, actor="agent", as_=None, tool="x", outcome="ok", now=5.0)
        outings.log_call(
            doc, path="/search", cache="miss", ms=3, started_by="agent", workspace_id=ws_id, now=5.0
        )
        self.assertEqual(doc, frozen)

    def test_the_document_is_plain_json(self):
        token = counter()
        doc, ws_id = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
        doc, _ = outings.open_outing(doc, ws_id, sample_args(), token=token, now=0.0)
        self.assertEqual(json.loads(json.dumps(doc)), doc)

    def test_an_unknown_workspace(self):
        self.assertEqual(refused(outings.workspace, outings.new_doc(), "ws_x")[0], "no_workspace")
        self.assertEqual(refused(outings.touch, outings.new_doc(), "ws_x", 0.0)[0], "no_workspace")

    def test_the_least_recently_seen_is_forgotten_first(self):
        token = counter()
        doc = outings.new_doc()
        made = []
        for i in range(5):
            doc, ws_id = outings.add_workspace(doc, token=token, now=100.0 + i)
            made.append(ws_id)
        doc = outings.touch(doc, made[0], 500.0)
        doc = outings.forget_least_recent(doc, cap=3)
        self.assertEqual([ws["id"] for ws in doc["workspaces"]], [made[0], made[3], made[4]])
        self.assertIs(outings.forget_least_recent(doc, cap=3), doc)

    def test_the_agents_calls_count_over_a_rolling_day(self):
        token = counter()
        doc, ws_id = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
        for t in (0.0, 5000.0, 90000.0):
            doc = outings.record_agent_call(doc, ws_id, t)
        ws = outings.workspace(doc, ws_id)
        self.assertEqual(outings.agent_calls_24h(ws, 90000.0), 2)
        self.assertEqual(outings.agent_calls_24h(ws, 90000.0 + 86400), 0)
        self.assertEqual(ws["agentCalls"], [5000.0, 90000.0])


class OpeningAnOuting(Base):
    def test_the_sample_group(self):
        out = self.outing()
        self.assertEqual(out["id"], "out_001")
        self.assertEqual([m["id"] for m in out["members"]], ["m1", "m2", "m3", "m4"])
        self.assertEqual([m["name"] for m in out["members"]], ["Noor", "Owen", "Pia", "Quinn"])
        favourites = [f["id"] for m in out["members"] for f in m["favourites"]]
        self.assertEqual(favourites, [f"f{i}" for i in range(1, 9)])
        self.assertEqual(out["conditions"], {
            "placeText": "New York City", "day": "friday", "priceMin": 2, "priceMax": 3, "radiusM": None,
            "kindTag": None, "setBy": "organiser",
        })
        self.assertEqual(out["kindQuery"], "restaurant")
        self.assertEqual(out["when"], "Fri 6 Nov, 7:30 pm")
        self.assertEqual(out["budget"], {"limit": 30, "spent": 0, "saved": 0, "stoppedBecause": None})
        untouched = (out["revision"], out["places"], out["comparison"], out["chosen"], out["drafts"])
        self.assertEqual(untouched, (1, [], None, None, []))
        self.assertEqual(len({m["token"] for m in out["members"]}), 4)
        first = out["members"][0]["favourites"][0]
        self.assertEqual(first, {
            "id": "f1", "name": "Lost in Translation", "namedBy": "member", "searched": False,
            "candidates": [], "resolved": None, "resolvedBy": None,
        })

    def test_a_second_outing_in_the_same_workspace(self):
        self.doc, second = outings.open_outing(
            self.doc, self.ws, sample_args(), token=self.token, now=2.0
        )
        self.assertEqual(second, "out_002")
        self.assertEqual(len(outings.workspace(self.doc, self.ws)["outings"]), 2)

    def test_the_call_limit_comes_from_the_caller(self):
        doc, out = outings.open_outing(
            self.doc, self.ws, sample_args(), token=self.token, now=2.0, call_limit=45
        )
        self.assertEqual(outings.outing(doc, self.ws, out)["budget"]["limit"], 45)

    def test_text_is_tidied_to_one_line(self):
        args = {**sample_args(), "label": "  Friday \n dinner  "}
        args["members"][0]["name"] = "No\nor"
        doc, out = outings.open_outing(self.doc, self.ws, args, token=self.token, now=2.0)
        opened = outings.outing(doc, self.ws, out)
        self.assertEqual((opened["label"], opened["members"][0]["name"]), ("Friday dinner", "No or"))

    def test_bad_arguments_are_refused_by_name(self):
        def args(**changes):
            return {**sample_args(), **changes}

        def members(count):
            return [{"name": f"P{i}", "favourites": []} for i in range(count)]

        def pair(first):
            return [first, {"name": "B"}]

        bad = {
            "members": [
                args(members=members(1)), args(members=members(7)), args(members="Noor"),
                args(members=pair({"name": "A" * 25})), args(members=[{"name": "A"}, {"name": "a"}]),
                args(members=pair({"name": "A", "favourites": "x"})),
                args(members=pair({"name": "A", "favourites": ["x" * 61]})),
                args(members=pair({"name": "A", "favourites": [""]})), args(members=["A", "B"]),
            ],
            "label": [args(label=""), args(label="x" * 61), args(label=None)],
            "place_text": [args(place_text=""), args(place_text="x" * 61), args(place_text=5)],
            "day": [args(day="Friday"), args(day="fri"), args(day=None)],
            "price_min": [
                args(price_min=0), args(price_min=5), args(price_min=True),
                args(price_min=3, price_max=2), args(price_min="2"),
            ],
            "radius_m": [args(radius_m=-1), args(radius_m=50001), args(radius_m=1.5)],
            "when": [args(when="x" * 41), args(when="")],
            "kind_query": [args(kind_query=" ")],
        }
        for field, cases in bad.items():
            for case in cases:
                with self.subTest(field=field, case=str(case)[:60]):
                    code, _ = refused(outings.open_outing, self.doc, self.ws, case, token=self.token, now=0.0)
                    self.assertEqual(code, "bad_arguments")

    def test_more_than_three_favourites(self):
        members = [{"name": "A", "favourites": ["1", "2", "3", "4"]}, {"name": "B"}]
        args = {**sample_args(), "members": members}
        result = refused(outings.open_outing, self.doc, self.ws, args, token=self.token, now=0.0)
        self.assertEqual(result, ("too_many_favourites", ""))

    def test_the_limits_at_their_edges_are_fine(self):
        members = [{"name": "N" * 24, "favourites": ["f" * 60] * 3}] + [{"name": f"P{i}"} for i in range(5)]
        args = {
            **sample_args(), "members": members, "label": "l" * 60, "place_text": "p" * 60,
            "when": "w" * 40, "price_min": 1, "price_max": 4, "radius_m": 50000,
        }
        doc, out = outings.open_outing(self.doc, self.ws, args, token=self.token, now=0.0)
        self.assertEqual(len(outings.outing(doc, self.ws, out)["members"]), 6)

    def test_no_such_workspace(self):
        result = refused(outings.open_outing, self.doc, "ws_x", sample_args(), token=self.token, now=0.0)
        self.assertEqual(result[0], "no_workspace")


class Lookups(Base):
    def test_found_and_not_found(self):
        out = self.outing()
        self.assertEqual(outings.member(out, "m2")["name"], "Owen")
        self.assertEqual(outings.favourite(outings.member(out, "m2"), "f3")["name"], "The Bear")
        self.assertEqual(refused(outings.outing, self.doc, self.ws, "out_009")[0], "unknown_outing")
        self.assertEqual(refused(outings.member, out, "m9")[0], "unknown_member")
        self.assertEqual(
            refused(outings.favourite, outings.member(out, "m2"), "f1")[0], "unknown_favourite"
        )

    def test_member_tokens_find_their_member(self):
        token = self.outing()["members"][2]["token"]
        self.assertEqual(outings.find_by_member_token(self.doc, token), (self.ws, self.out, "m3"))
        self.assertIsNone(outings.find_by_member_token(self.doc, "nope"))


class Candidates(Base):
    def test_stored_with_the_fields_the_card_needs(self):
        found = candidates("a", "b")
        self.doc = outings.store_candidates(self.doc, self.ws, self.out, "m1", "f1", found)
        stored = outings.favourite(outings.member(self.outing(), "m1"), "f1")["candidates"]
        self.assertEqual(stored[0], {
            "entityId": "cand-a", "name": "a", "type": "urn:entity:movie", "popularity": 0.5,
            "disambiguation": None,
        })
        self.assertEqual(self.outing()["revision"], 2)

    def test_a_new_search_clears_an_earlier_resolution(self):
        self.search_all()
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m1", "f1", "cand-f1-a", "member")
        again = candidates("f1-a")
        self.doc = outings.store_candidates(self.doc, self.ws, self.out, "m1", "f1", again)
        fav = outings.favourite(outings.member(self.outing(), "m1"), "f1")
        self.assertEqual((fav["resolved"], fav["resolvedBy"]), (None, None))


class Resolving(Base):
    def test_resolve_records_who_resolved(self):
        self.search_all()
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m2", "f3", "cand-f3-b", "organiser_for")
        fav = outings.favourite(outings.member(self.outing(), "m2"), "f3")
        self.assertEqual((fav["resolved"], fav["resolvedBy"]), ("cand-f3-b", "organiser_for"))

    def test_only_a_candidate_this_favourite_returned_can_be_resolved(self):
        self.search_all()
        self.assertEqual(
            self.code(outings.resolve, "m2", "f3", "cand-f1-a", "member"), "unknown_entity"
        )
        self.assertEqual(self.code(outings.resolve, "m2", "f3", "made-up", "member"), "unknown_entity")

    def test_the_resolver_must_be_named(self):
        self.search_all()
        self.assertEqual(self.code(outings.resolve, "m1", "f1", "cand-f1-a", "agent"), "bad_arguments")

    def test_a_failed_change_leaves_the_document_alone(self):
        self.search_all()
        before = copy.deepcopy(self.doc)
        self.code(outings.resolve, "m1", "f1", "nope", "member")
        self.assertEqual(self.doc, before)

    def test_a_resolution_stays_in_its_own_outing(self):
        self.search_all()
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m1", "f1", "cand-f1-a", "member")
        self.doc, second = outings.open_outing(
            self.doc, self.ws, sample_args(), token=self.token, now=2.0
        )
        member = outings.member(outings.outing(self.doc, self.ws, second), "m1")
        again = outings.favourite(member, "f1")
        self.assertEqual((again["candidates"], again["resolved"], again["resolvedBy"]), ([], None, None))

    def test_resolving_marks_a_comparison_stale_and_bumps_the_revision(self):
        self.search_all()
        self.stale_marker()
        before = self.outing()["revision"]
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m1", "f1", "cand-f1-a", "member")
        self.assertTrue(self.outing()["comparison"]["stale"])
        self.assertEqual(self.outing()["revision"], before + 1)

    def test_which_members_still_need_a_match(self):
        self.search_all()
        self.assertEqual(outings.members_without_a_match(self.outing()), ["m1", "m2", "m3", "m4"])
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m2", "f3", "cand-f3-a", "member")
        self.doc = outings.resolve(self.doc, self.ws, self.out, "m2", "f4", "cand-f4-a", "organiser_for")
        out = self.outing()
        self.assertEqual(outings.members_without_a_match(out), ["m1", "m3", "m4"])
        owen = outings.member(out, "m2")
        self.assertEqual(outings.resolved_ids(owen), ["cand-f3-a", "cand-f4-a"])
        self.assertEqual(outings.all_resolved_ids(out), ["cand-f3-a", "cand-f4-a"])
        self.assertEqual(outings.member_entities(out)["m2"], ["cand-f3-a", "cand-f4-a"])
        self.assertEqual(
            outings.favourite_by_entity(owen), {"cand-f3-a": "f3", "cand-f4-a": "f4"}
        )

    def test_a_shared_entity_is_listed_once(self):
        self.search_all()
        for member, fav in (("m1", "f1"), ("m2", "f3")):
            found = candidates("same")
            self.doc = outings.store_candidates(self.doc, self.ws, self.out, member, fav, found)
            self.doc = outings.resolve(self.doc, self.ws, self.out, member, fav, "cand-same", "member")
        self.assertEqual(outings.all_resolved_ids(self.outing()), ["cand-same"])


class OwnFavourites(Base):
    def test_a_member_may_add_up_to_three_in_all(self):
        self.doc = outings.add_favourite(self.doc, self.ws, self.out, "m1", "  A New Thing ", "member")
        fav = outings.member(self.outing(), "m1")["favourites"][-1]
        self.assertEqual(fav, {
            "id": "f9", "name": "A New Thing", "namedBy": "member", "searched": False,
            "candidates": [], "resolved": None, "resolvedBy": None,
        })
        self.assertEqual(self.code(outings.add_favourite, "m1", "Another", "member"), "too_many_favourites")

    def test_provenance_and_text_are_checked(self):
        self.assertEqual(self.code(outings.add_favourite, "m1", "x", "agent"), "bad_arguments")
        self.assertEqual(self.code(outings.add_favourite, "m1", "x" * 61, "member"), "bad_arguments")
        self.assertEqual(self.code(outings.add_favourite, "m9", "x", "member"), "unknown_member")

    def test_the_organiser_can_name_one_on_a_members_behalf(self):
        args = {**sample_args(), "members": [{"name": "A"}, {"name": "B", "favourites": ["x"]}]}
        doc, out = outings.open_outing(self.doc, self.ws, args, token=self.token, now=2.0)
        doc = outings.add_favourite(doc, self.ws, out, "m2", "y", "organiser_for")
        favourites = outings.member(outings.outing(doc, self.ws, out), "m2")["favourites"]
        self.assertEqual(
            [(f["name"], f["namedBy"]) for f in favourites], [("x", "member"), ("y", "organiser_for")]
        )


class Conditions(Base):
    tags = [
        records.Tag("urn:tag:synthetic:restaurant", "Restaurant", "k"),
        records.Tag("urn:tag:synthetic:bar", "Bar", "k"),
    ]

    def test_a_kind_must_be_a_tag_qloo_returned(self):
        made_up = {"kind_tag": "urn:tag:made:up"}
        self.assertEqual(self.code(outings.set_conditions, made_up), "unknown_tag")
        self.doc = outings.store_known_tags(self.doc, self.ws, self.out, self.tags)
        self.assertEqual(self.code(outings.set_conditions, made_up), "unknown_tag")
        self.doc = outings.set_conditions(self.doc, self.ws, self.out, {"kind_tag": "urn:tag:synthetic:bar"})
        self.assertEqual(
            self.outing()["conditions"]["kindTag"], {"id": "urn:tag:synthetic:bar", "name": "Bar"}
        )
        self.doc = outings.set_conditions(self.doc, self.ws, self.out, {"kind_tag": None})
        self.assertIsNone(self.outing()["conditions"]["kindTag"])

    def test_changes_merge_and_none_clears_a_price(self):
        changes = {"day": "saturday", "price_max": None, "radius_m": 800}
        self.doc = outings.set_conditions(self.doc, self.ws, self.out, changes)
        c = self.outing()["conditions"]
        self.assertEqual(
            (c["day"], c["priceMin"], c["priceMax"], c["radiusM"], c["placeText"]),
            ("saturday", 2, None, 800, "New York City"),
        )

    def test_the_result_must_still_be_valid(self):
        for changes in ({"price_min": 4}, {"day": "someday"}, {"place_text": ""}, {"radius_m": -3}):
            with self.subTest(changes=changes):
                self.assertEqual(self.code(outings.set_conditions, changes), "bad_arguments")

    def test_only_conditions_can_be_changed(self):
        for changes in ({}, {"label": "x"}, {"day": "monday", "revision": 9}):
            with self.subTest(changes=changes):
                self.assertEqual(self.code(outings.set_conditions, changes), "bad_arguments")

    def test_a_change_makes_the_comparison_stale(self):
        self.stale_marker()
        self.doc = outings.set_conditions(self.doc, self.ws, self.out, {"day": "sunday"})
        self.assertTrue(self.outing()["comparison"]["stale"])


class Logs(Base):
    def test_activity_entries(self):
        self.doc = outings.log_activity(
            self.doc, self.ws, actor="person", as_="organiser", tool="resolve_match", outcome="ok", now=1000.0
        )
        self.assertEqual(outings.workspace(self.doc, self.ws)["activityLog"], [{
            "ts": "1970-01-01T00:16:40Z", "actor": "person", "as": "organiser", "tool": "resolve_match",
            "outcome": "ok",
        }])

    def test_activity_is_capped(self):
        cap = outings.MAX_LOGGED_ACTIVITY
        for i in range(cap + 5):
            self.doc = outings.log_activity(
                self.doc, self.ws, actor="agent", as_=None, tool=str(i), outcome="ok", now=0.0
            )
        log = outings.workspace(self.doc, self.ws)["activityLog"]
        self.assertEqual((len(log), log[-1]["tool"]), (cap, str(cap + 4)))

    def test_a_call_entry_holds_no_name_or_query_value(self):
        self.doc = outings.log_call(
            self.doc, path="/v2/insights", cache="miss", ms=640, started_by="agent",
            workspace_id=self.ws, now=0.0,
        )
        self.assertEqual(self.doc["calls"], [{
            "ts": "1970-01-01T00:00:00Z", "path": "/v2/insights", "cache": "miss", "ms": 640,
            "startedBy": "agent", "workspace": self.ws,
        }])

    def test_calls_are_capped(self):
        for _ in range(outings.MAX_LOGGED_CALLS + 3):
            self.doc = outings.log_call(
                self.doc, path="/search", cache="hit", ms=0, started_by="person",
                workspace_id=self.ws, now=0.0,
            )
        self.assertEqual(len(self.doc["calls"]), outings.MAX_LOGGED_CALLS)


class Scenario(unittest.TestCase):
    def test_the_sample_group_turns_into_open_outing_arguments(self):
        args = sample_args()
        self.assertEqual(
            args["members"][0], {"name": "Noor", "favourites": ["Lost in Translation", "Khruangbin"]}
        )
        self.assertNotIn("domain", json.dumps(args))
        self.assertEqual((args["day"], args["price_min"], args["price_max"]), ("friday", 2, 3))


if __name__ == "__main__":
    unittest.main()
