"""Page v1: the flow the page runs, driven over HTTP through the very endpoints and tool names
the page's own script uses, and a read of that script and its files for what must never be in them."""
import os
import re
import unittest

from common_ground import agent_tools, person_verbs, web
from tests.served import Browser, Served, sample_walk

WEB = web.WEB_DIR


def source(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


class Flow(unittest.TestCase):
    def setUp(self):
        self.served = Served()
        self.served.__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)

    def test_the_sample_group_runs_from_the_form_to_the_cards(self):
        browser = Browser(self.served)
        outing = sample_walk(browser)
        state = browser.state()
        out = state["outings"][-1]
        self.assertEqual(outing, "out_001")
        self.assertEqual((out["budget"]["spent"], out["budget"]["limit"]), (14, 30))
        self.assertFalse(out["comparison"]["stale"])
        self.assertEqual(out["comparison"]["outcome"], "common")
        self.assertEqual(out["budget"]["stoppedBecause"], "done")
        cards = [p for p in out["places"] if p["status"] in ("common", "near")]
        self.assertGreaterEqual(len(cards), 5)
        for place in cards:
            self.assertEqual([m["member"] for m in place["perMember"]], ["m1", "m2", "m3", "m4"])

    def test_every_card_that_rests_on_the_organisers_resolution_says_whose(self):
        browser = Browser(self.served)
        sample_walk(browser)
        out = browser.state()["outings"][-1]
        resolved_by = {m["id"]: {f["resolvedBy"] for f in m["favourites"]} for m in out["members"]}
        self.assertEqual(resolved_by["m1"], {"member"})
        self.assertEqual(resolved_by["m2"], {"organiser_for"})
        for place in (p for p in out["places"] if p["status"] in ("common", "near")):
            flags = {m["member"]: m["restsOnOrganiserResolution"] for m in place["perMember"]}
            self.assertEqual(flags, {"m1": False, "m2": True, "m3": True, "m4": True})

    def test_members_who_resolve_from_their_own_link_leave_no_label_on_their_bars(self):
        browser = Browser(self.served)
        sample_walk(browser, resolve=False)
        state = browser.state()
        out = state["outings"][-1]
        first = out["members"][0]["favourites"][0]
        browser.ok("resolve_match", {"outing_id": "out_001", "member_id": "m1", "favourite_id": first["id"],
                                     "entity_id": first["candidates"][0]["entityId"]})
        for member in out["members"][1:]:
            token = state["memberLinks"]["out_001"][member["id"]].rsplit("/", 1)[1]
            for favourite in member["favourites"]:
                asked = {"outing_id": "out_001", "member_id": member["id"], "favourite_id": favourite["id"],
                         "entity_id": favourite["candidates"][0]["entityId"]}
                reply = self.served.call(
                    "POST", f"/api/member/{token}/dispatch", {"tool": "resolve_match", "args": asked},
                    headers={"Sec-Fetch-Site": "same-origin", "Origin": self.served.origin})
                self.assertEqual(reply.json["result"]["resolvedBy"], "member")
        out = browser.state()["outings"][-1]
        second = out["members"][0]["favourites"][1]
        browser.ok("resolve_match", {"outing_id": "out_001", "member_id": "m1", "favourite_id": second["id"],
                                     "entity_id": second["candidates"][0]["entityId"]})
        tags = out["knownTags"]
        browser.ok("change_conditions", {"outing_id": "out_001", "kind_tag": tags[0]["id"]})
        browser.ok("run_comparison", {"outing_id": "out_001"})
        out = browser.state()["outings"][-1]
        for place in (p for p in out["places"] if p["status"] in ("common", "near")):
            self.assertFalse(any(m["restsOnOrganiserResolution"] for m in place["perMember"]))

    def test_the_agent_address_runs_the_same_comparison_and_stops_where_a_person_must_act(self):
        page = Browser(self.served)
        sample_walk(page)
        page_out = page.state()["outings"][-1]

        other = Browser(self.served)
        other.open()
        address = other.state()["agentAddress"]
        token = address.rsplit("/", 1)[1]
        args = other.get("/api/sample").json["args"]

        def agent(tool, arguments):
            reply = other.served.call("POST", f"/agent/{token}/dispatch", {"tool": tool, "args": arguments})
            self.assertEqual(reply.status, 200)
            return reply.json

        opened = agent("open_outing", args)["result"]["outingId"]
        for member in other.state()["outings"][-1]["members"]:
            for favourite in member["favourites"]:
                self.assertTrue(agent("look_up_favourite", {
                    "outing_id": opened, "member_id": member["id"], "favourite_id": favourite["id"]})["ok"])
        tags = agent("look_up_kind", {"outing_id": opened, "query": args["kind_query"]})["result"]["tags"]
        self.assertEqual(agent("run_comparison", {"outing_id": opened})["outcome"], "needs_favourites")
        self.assertEqual(agent("resolve_match", {"outing_id": opened})["outcome"], "not_a_tool")
        self.assertEqual(agent("change_conditions", {"outing_id": opened})["outcome"], "not_a_tool")

        for member in other.state()["outings"][-1]["members"]:
            for favourite in member["favourites"]:
                other.ok("resolve_match", {"outing_id": opened, "member_id": member["id"],
                                           "favourite_id": favourite["id"],
                                           "entity_id": favourite["candidates"][0]["entityId"]})
        other.ok("change_conditions", {"outing_id": opened, "kind_tag": tags[0]["id"]})
        done = agent("run_comparison", {"outing_id": opened})
        self.assertTrue(done["ok"], done)
        agent_out = other.state()["outings"][-1]
        def standing(out):
            return [(p["name"], p["status"]) for p in out["places"]]

        self.assertEqual(standing(agent_out), standing(page_out))
        self.assertEqual(agent_out["budget"]["spent"], page_out["budget"]["spent"])


AS_AGENT = {"X-Common-Ground-As": "agent"}


class Deciding(unittest.TestCase):
    """The calls the page makes after the cards: pick, draft, sign off, and the organiser's other controls."""

    def setUp(self):
        self.served = Served()
        self.served.__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)
        self.browser = Browser(self.served)
        self.oid = sample_walk(self.browser)

    def out(self):
        return self.browser.state()["outings"][-1]

    def place(self, status):
        return next(p for p in self.out()["places"] if p["status"] == status)

    def args(self, **extra):
        return {"outing_id": self.oid, **extra}

    def pick_args(self, place, **extra):
        return self.args(place_id=place["entityId"], revision=self.out()["revision"], **extra)

    def draft(self, place, kind):
        return self.browser.ok("write_draft", self.args(place_id=place["entityId"], kind=kind))

    def sign_off(self, sender, draft_id="d1"):
        return self.browser.act("sign_off_message", self.args(
            draft_id=draft_id, sender_name=sender, revision=self.out()["revision"]))

    def test_pick_a_common_place_draft_both_messages_sign_off_and_read_the_text(self):
        pick = self.place("common")
        picked = self.browser.ok("pick_place", self.pick_args(pick))
        self.assertEqual(picked["chosen"], pick["name"])
        self.assertEqual(self.out()["chosen"]["placeId"], pick["entityId"])
        for kind in ("invitation", "booking_request"):
            made = self.draft(pick, kind)
            self.assertTrue(made["text"].startswith("DRAFT. Not signed off. Do not send."))
            self.assertEqual(made["state"], "draft")
        self.assertEqual(self.browser.get(f"/api/message/{self.oid}-d1.txt").status, 404)
        self.assertTrue(self.sign_off(" Noor ")["ok"])
        text = self.browser.get(f"/api/message/{self.oid}-d1.txt")
        self.assertEqual(text.status, 200)
        self.assertNotIn("DRAFT", text.text)
        self.assertTrue(text.text.rstrip().endswith("Noor"))
        self.assertEqual(self.browser.get(f"/api/message/{self.oid}-d2.txt").status, 404)
        shown = {d["draftId"]: d for d in self.out()["drafts"]}
        self.assertEqual((shown["d1"]["state"], shown["d1"]["signedOffBy"]), ("released", "Noor"))
        self.assertEqual(shown["d2"]["state"], "draft")

    def test_a_sign_off_needs_a_named_sender(self):
        pick = self.place("common")
        self.browser.ok("pick_place", self.pick_args(pick))
        self.draft(pick, "invitation")
        for sender in ("", "   ", None):
            self.assertEqual(self.sign_off(sender)["outcome"], "sender_missing")
        self.assertEqual(self.out()["drafts"][0]["state"], "draft")

    def test_a_near_place_is_picked_only_after_the_organiser_says_who_it_leaves_out(self):
        near = self.place("near")
        self.assertTrue(near["leftOut"])
        self.assertEqual(self.browser.act("pick_place", self.pick_args(near))["outcome"],
                         "left_out_unacknowledged")
        self.assertIsNone(self.out()["chosen"])
        said = self.browser.ok("pick_place", self.pick_args(near, acknowledge_left_out=near["leftOut"]))
        self.assertEqual(said["leftOut"], near["leftOut"])
        self.assertEqual(self.out()["chosen"]["acknowledged"], near["leftOut"])

    def test_changing_a_condition_marks_the_comparison_out_of_date_and_a_pick_is_refused(self):
        pick = self.place("common")
        self.browser.ok("change_conditions", self.args(price_min=1, price_max=4))
        out = self.out()
        self.assertTrue(out["comparison"]["stale"])
        self.assertEqual(out["conditions"]["priceMin"], 1)
        self.assertEqual(self.browser.act("pick_place", self.pick_args(pick))["outcome"], "stale_comparison")
        self.browser.ok("run_comparison", self.args())
        self.assertFalse(self.out()["comparison"]["stale"])

    def test_ruling_a_place_out_keeps_it_listed_with_the_reason_and_putting_it_back_restores_it(self):
        pick = self.place("common")
        self.browser.ok("rule_out_place", self.args(place_id=pick["entityId"], reason="too far for Pia"))
        ruled = next(p for p in self.out()["places"] if p["entityId"] == pick["entityId"])
        self.assertEqual((ruled["status"], ruled["ruledOut"]["reason"]), ("ruled_out", "too far for Pia"))
        blank = self.browser.act("rule_out_place", self.args(place_id=pick["entityId"], reason=" "))
        self.assertEqual(blank["outcome"], "bad_arguments")
        self.browser.ok("rule_out_place", self.args(place_id=pick["entityId"], undo=True))
        back = next(p for p in self.out()["places"] if p["entityId"] == pick["entityId"])
        self.assertEqual(back["status"], "common")

    def test_the_limit_is_raised_by_the_organiser_and_only_up_to_the_most(self):
        self.browser.ok("lift_call_limit", self.args(limit=35))
        self.assertEqual(self.out()["budget"]["limit"], 35)
        for limit in (35, 61):
            self.assertEqual(self.browser.act("lift_call_limit", self.args(limit=limit))["outcome"],
                             "bad_arguments")
        self.assertEqual(self.browser.state()["callLimit"], {"default": 30, "max": 60})

    def test_a_search_that_stops_at_the_limit_says_so_and_the_raised_limit_carries_it_on(self):
        small = Browser(self.served)
        oid = sample_walk(small, compare=False)
        asked = small.ok("run_comparison", {"outing_id": oid, "max_calls": 11})
        self.assertEqual((asked["stoppedBecause"], asked["unranked"] != []), ("over_limit", True))
        again = small.ok("run_comparison", {"outing_id": oid, "max_calls": 11})
        self.assertEqual((again["stoppedBecause"], again["callsThisRun"]), ("over_limit", 0))
        small.ok("lift_call_limit", {"outing_id": oid, "limit": 40})
        done = small.ok("run_comparison", {"outing_id": oid})
        self.assertEqual((done["stoppedBecause"], done["callsSpent"]), ("done", 14))

    def test_every_human_verb_run_with_the_agent_header_is_not_a_tool_and_changes_nothing(self):
        pick = self.place("common")
        before = self.out()
        calls = {
            "pick_place": self.pick_args(pick),
            "sign_off_message": self.args(draft_id="d1", sender_name="Noor", revision=1),
            "change_conditions": self.args(day="monday"),
            "rule_out_place": self.args(place_id=pick["entityId"], reason="no"),
            "lift_call_limit": self.args(limit=40),
            "resolve_match": self.args(member_id="m1", favourite_id="f1", entity_id="x"),
            "add_own_favourite": self.args(member_id="m1", name="x"),
        }
        self.assertEqual(set(calls), set(person_verbs.VERBS))
        for verb, args in calls.items():
            with self.subTest(verb):
                self.assertEqual(self.browser.act(verb, args, **AS_AGENT)["outcome"], "not_a_tool")
        self.assertEqual(self.out(), before)

    def member(self, member_id):
        token = self.browser.state()["memberLinks"][self.oid][member_id].rsplit("/", 1)[1]
        own = {"Sec-Fetch-Site": "same-origin", "Origin": self.served.origin}

        def call(method, tool=None, **args):
            path = f"/api/member/{token}/" + ("dispatch" if tool else "state")
            body = {"tool": tool, "args": self.args(member_id=member_id, **args)} if tool else None
            return self.served.call(method, path, body, headers=own).json

        return call

    def test_a_member_adds_a_favourite_from_their_own_link_and_it_waits_for_a_search_nobody_has_run(self):
        mine = self.member("m3")
        added = mine("POST", "add_own_favourite", name="Dune Part Two")
        self.assertEqual((added["ok"], added["result"]["namedBy"]), (True, "member"))
        fresh = mine("GET")["member"]["favourites"][-1]
        self.assertEqual((fresh["name"], fresh["searched"]), ("Dune Part Two", False))
        self.assertEqual(fresh["candidates"], [])
        search = {"favourite_id": fresh["id"]}
        self.assertEqual(mine("POST", "look_up_favourite", **search)["outcome"], "wrong_actor")
        self.browser.ok("look_up_favourite", self.args(member_id="m3", **search))
        self.assertTrue(mine("GET")["member"]["favourites"][-1]["candidates"])

    def test_the_organiser_adds_a_favourite_for_a_person_and_it_is_recorded_as_theirs_to_confirm(self):
        added = self.browser.ok("add_own_favourite", self.args(member_id="m2", name="Heat"))
        self.assertEqual(added["namedBy"], "organiser_for")
        mine = self.browser.ok("add_own_favourite", self.args(member_id="m1", name="Heat"))
        self.assertEqual(mine["namedBy"], "member")
        full = self.browser.act("add_own_favourite", self.args(member_id="m1", name="Again"))
        self.assertEqual(full["outcome"], "too_many_favourites")

    def test_a_favourite_nobody_searched_is_left_out_of_the_comparison_and_says_so(self):
        self.browser.ok("add_own_favourite", self.args(member_id="m2", name="Heat"))
        favourites = self.out()["members"][1]["favourites"]
        self.assertEqual([f["searched"] for f in favourites], [True, True, False])
        self.assertEqual(self.browser.ok("run_comparison", self.args())["outcome"], "common")


class PageSource(unittest.TestCase):
    def test_the_script_calls_only_endpoints_and_names_that_exist(self):
        script = source("app.js")
        paths = set(re.findall(r'"(/api/[a-z/]+)"', script))
        self.assertEqual(paths, {"/api/dispatch", "/api/state", "/api/sample", "/api/calls", "/api/tools"})
        member = set(re.findall(r"`(/api/member/\$\{token\}[a-z/]*)`", script))
        self.assertEqual(member, {"/api/member/${token}/state", "/api/member/${token}"})
        self.assertIn("${page.base}/dispatch", script)
        self.assertIn("/api/message/${out.id}-${draft.draftId}.txt", script)
        named = set(re.findall(r'act\([A-Za-z]+, "([a-z_]+)"', script))
        known = set(agent_tools.TOOLS) | set(person_verbs.VERBS)
        self.assertTrue(named, "the script names no tool")
        self.assertLessEqual(named, known)
        walk = {"open_outing", "look_up_favourite", "look_up_kind", "run_comparison", "resolve_match",
                "write_draft"}
        self.assertTrue(walk | set(person_verbs.VERBS) <= named)

    def test_every_call_of_a_human_verb_sits_in_a_button_the_banner_logic_can_disable(self):
        script = source("app.js")
        calls = list(re.finditer(r'act\(\s*[A-Za-z]+,\s*"([a-z_]+)"', script))
        run = set()
        for call in calls:
            verb = call.group(1)
            if verb not in person_verbs.VERBS:
                continue
            run.add(verb)
            button = script[script.rindex('el("button"', 0, call.start()):call.start()]
            with self.subTest(verb=verb, at=call.start()):
                self.assertIn('"data-needs-person": true', button)
        self.assertEqual(run, set(person_verbs.VERBS), "the page offers a control for every human verb")
        self.assertIn('hasAttribute("data-needs-person") && state.gate', script)

    def test_a_human_verb_is_named_in_the_script_only_where_it_is_run_or_refused_for_the_agent(self):
        script = source("app.js")
        console = script[script.index("function renderConsole"):script.index("function renderOrganiser")]
        self.assertNotIn("act(", console)
        self.assertIn("AS_AGENT", console)
        self.assertIn('const AS_AGENT = { "X-Common-Ground-As": "agent" };', script)
        rest = re.sub(r'act\(\s*[A-Za-z]+,\s*"[a-z_]+"', "", script)
        rest = rest.replace(console, "")
        for verb in sorted(person_verbs.VERBS):
            self.assertNotIn(f'"{verb}"', rest)

    def test_no_file_loads_anything_from_elsewhere_and_nothing_is_inline(self):
        for name in ("index.html", "member.html", "app.js", "app.css"):
            text = source(name)
            with self.subTest(name):
                self.assertIsNone(re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//", text), name)
                self.assertIsNone(re.search(r"url\(\s*[\"']?(https?:)?//", text), name)
                self.assertNotIn("@import", text)
                self.assertNotIn("googleapis", text)
        for name in ("index.html", "member.html"):
            text = source(name)
            with self.subTest(name):
                self.assertEqual(re.findall(r"<script[^>]*>", text), ['<script src="/app.js" defer>'])
                links = re.findall(r"<link[^>]*>", text)
                self.assertEqual(links, ['<link rel="stylesheet" href="/app.css">'])
                self.assertNotIn("<style", text)
                self.assertIsNone(re.search(r"\sstyle\s*=", text))
                self.assertIsNone(re.search(r"\son[a-z]+\s*=", text))
                self.assertIn('name="viewport"', text)
                self.assertIn('<html lang="en">', text)

    def test_the_script_never_builds_markup_from_text(self):
        script = source("app.js")
        banned = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                  "localStorage", "sessionStorage")
        for name in banned:
            self.assertNotIn(name, script)

    def test_every_form_control_in_the_page_has_a_label(self):
        text = source("index.html")
        ids = set(re.findall(r'<(?:input|select)[^>]*\sid="([^"]+)"', text))
        labelled = set(re.findall(r'<label[^>]*\sfor="([^"]+)"', text))
        self.assertTrue(ids)
        self.assertEqual(ids - labelled, set())
        template = text[text.index("<template"):text.index("</template>")]
        self.assertEqual(len(re.findall(r"<label>", template)), len(re.findall(r"<input", template)))

    def test_the_palette_has_a_light_and_a_dark_form_and_a_phone_layout(self):
        css = source("app.css")
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertRegex(css, r"@media \(max-width: 3\d(\.\d+)?rem\)")
        self.assertIn(":focus-visible", css)
        self.assertRegex(css, r"min-height:\s*2\.75rem")
        self.assertIn("overflow-wrap: anywhere", css)


if __name__ == "__main__":
    unittest.main()
