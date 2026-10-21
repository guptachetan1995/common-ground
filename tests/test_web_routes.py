"""Every row of the route table over a real server on port 0: host, request label, origin,
credential, content type and size, the limits, and what each answer may and may not contain."""
import contextlib
import io
import json
import re
import socket
import unittest

from common_ground import agent_tools, outings, person_verbs, web
from tests.served import Browser, Served, sample_walk
from tests.test_outings import sample_args

VERBS = sorted(person_verbs.VERBS)
WORKSPACE_ID = re.compile(r"ws_[0-9a-f]{32}")
STATIC = ("/", "/app.js", "/app.css")
LABELS = {"same-site": 403, "cross-site": 403, "elsewhere": 403, "none": 200, "same-origin": 200}


def person_headers(served):
    return {"Sec-Fetch-Site": "same-origin", "Origin": served.origin}


class Routes(unittest.TestCase):
    def setUp(self):
        self.served = Served()
        self.served.__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)
        self.browser = Browser(self.served)

    def call(self, *args, **kwargs):
        return self.served.call(*args, **kwargs)


class Health(Routes):
    def test_healthz_answers_ok_with_no_state_and_to_any_host(self):
        for host in (None, "elsewhere.example", ""):
            with self.subTest(host):
                reply = self.call("GET", "/healthz", host=host)
                self.assertEqual((reply.status, reply.text), (200, "ok\n"))
        self.assertEqual(self.call("HEAD", "/healthz").status, 200)
        self.assertEqual(self.call("POST", "/healthz", {}).status, 405)
        self.assertNotIn("set-cookie", self.call("GET", "/healthz").headers)

    def test_a_foreign_or_missing_host_is_refused_everywhere_else(self):
        self.browser.open()
        token = self.browser.state()["agentAddress"].rsplit("/", 1)[1]
        paths = [*STATIC, "/api/state", "/api/tools", "/api/calls", "/api/sample", "/m/abc",
                 f"/agent/{token}/tools", f"/agent/{token}/mcp", "/api/member/abc/state"]
        for host in ("elsewhere.example", "127.0.0.1.evil.example", "", "[::2]:80"):
            for path in paths:
                with self.subTest(host=host, path=path):
                    reply = self.call("GET", path, host=host, headers={"Cookie": self.browser.cookie})
                    self.assertEqual(reply.status, 403)
                    self.assertEqual(reply.json["outcome"], "bad_host")
                    self.assertNotIn("set-cookie", reply.headers)

    def test_the_loopback_names_and_ports_are_accepted(self):
        for host in ("localhost", "localhost:8761", "127.0.0.1", "[::1]:9000"):
            with self.subTest(host):
                self.assertEqual(self.call("GET", "/app.css", host=host).status, 200)


class Pages(Routes):
    def test_the_first_visit_sets_the_cookie_and_the_second_does_not(self):
        first = self.browser.open()
        cookie = first.headers["set-cookie"]
        self.assertRegex(cookie, r"^cg_w=ws_[0-9a-f]{32}; HttpOnly; SameSite=Strict; Path=/$")
        self.assertNotIn("Secure", cookie)
        self.assertNotIn("Max-Age", cookie)
        self.assertNotIn("Expires", cookie)
        again = self.call("GET", "/", headers={"Cookie": self.browser.cookie})
        self.assertNotIn("set-cookie", again.headers)

    def test_an_unknown_cookie_is_replaced(self):
        reply = self.call("GET", "/", headers={"Cookie": "cg_w=ws_" + "0" * 32})
        self.assertIn("cg_w=ws_", reply.headers["set-cookie"])
        self.assertNotIn("0" * 32, reply.headers["set-cookie"])

    def test_the_cookie_is_secure_off_loopback(self):
        s = Served(allowed_hosts=("127.0.0.1", "localhost", "[::1]", "demo.example"))
        with s:
            reply = s.call("GET", "/", host="demo.example")
            cookie = reply.headers["set-cookie"]
            self.assertTrue(cookie.endswith("; HttpOnly; SameSite=Strict; Path=/; Secure"), cookie)

    def test_a_visitor_arriving_from_a_link_gets_the_page(self):
        for label in ("cross-site", "same-site", "none", "same-origin"):
            with self.subTest(label):
                reply = self.call("GET", "/", headers={"Sec-Fetch-Site": label})
                self.assertEqual(reply.status, 200)
                self.assertTrue(reply.headers["content-type"].startswith("text/html"))

    def test_static_files_have_their_types(self):
        kinds = {"/app.js": "text/javascript", "/app.css": "text/css"}
        for path, kind in kinds.items():
            with self.subTest(path):
                reply = self.call("GET", path)
                self.assertTrue(reply.headers["content-type"].startswith(kind))
                self.assertNotIn("set-cookie", reply.headers)

    def test_unknown_paths_and_wrong_methods(self):
        self.assertEqual(self.call("GET", "/nope").status, 404)
        self.assertEqual(self.call("GET", "/../etc/passwd").status, 404)
        self.assertEqual(self.call("GET", "/web/app.js").status, 404)
        post = self.call("POST", "/", {})
        self.assertEqual((post.status, post.headers["allow"]), (405, "GET"))
        self.assertEqual(self.call("DELETE", "/app.js").status, 405)
        self.assertEqual(self.call("OPTIONS", "/api/dispatch").status, 405)

    def test_every_answer_carries_the_strict_headers_and_no_cross_origin_header(self):
        self.browser.open()
        answers = [
            self.call("GET", "/"), self.call("GET", "/app.js"), self.call("GET", "/nope"),
            self.call("GET", "/healthz"), self.call("POST", "/api/dispatch", {}),
            self.browser.get("/api/state"), self.call("GET", "/", host="elsewhere.example"),
        ]
        for reply in answers:
            with self.subTest(reply.status):
                self.assertEqual(reply.headers["content-security-policy"], web.CSP)
                self.assertEqual(reply.headers["x-content-type-options"], "nosniff")
                self.assertEqual(reply.headers["referrer-policy"], "no-referrer")
                self.assertEqual(reply.headers["cache-control"], "no-store")
                self.assertFalse([h for h in reply.headers if h.startswith("access-control")])

    def test_the_csp_is_the_one_the_plan_pins(self):
        self.assertEqual(
            web.CSP,
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )

    def test_the_sample_is_the_scenario_files_arguments(self):
        with open(web.SAMPLE_FILE, encoding="utf-8") as fh:
            expected = outings.scenario_args(json.load(fh))
        self.assertEqual(self.call("GET", "/api/sample").json, {"args": expected})

    def test_a_member_page_needs_a_valid_token(self):
        self.assertEqual(self.call("GET", "/m/not-a-token").status, 404)
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        link = self.browser.state()["memberLinks"]["out_001"]["m2"]
        path = "/" + link.split("/", 3)[3]
        reply = self.call("GET", path, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(reply.status, 200)
        self.assertTrue(reply.headers["content-type"].startswith("text/html"))
        self.assertNotIn("set-cookie", reply.headers)


class State(Routes):
    def test_an_api_route_without_the_cookie_is_401(self):
        for path in ("/api/state", "/api/tools", "/api/calls", "/api/message/out_001-d1.txt"):
            with self.subTest(path):
                reply = self.call("GET", path, headers={"Sec-Fetch-Site": "same-origin"})
                self.assertEqual((reply.status, reply.json["outcome"]), (401, "no_workspace"))
        self.assertEqual(self.call("POST", "/api/dispatch", {"tool": "spend_report"}).status, 401)

    def test_the_request_label_decides_the_actor_and_says_why(self):
        self.browser.open()
        cookie = {"Cookie": self.browser.cookie}
        cases = [
            ({"Sec-Fetch-Site": "same-origin"}, "person", "same_origin"),
            ({"Sec-Fetch-Site": "none"}, "agent", "typed_address"),
            ({}, "agent", "no_fetch_metadata"),
            ({"Sec-Fetch-Site": "same-origin", "X-Common-Ground-As": "agent"}, "agent", "agent_header"),
            ({"Sec-Fetch-Site": "same-origin", "X-Common-Ground-As": "person"}, "person", "same_origin"),
        ]
        for extra, actor, why in cases:
            with self.subTest(extra):
                state = self.call("GET", "/api/state", headers={**cookie, **extra}).json
                self.assertEqual((state["actor"], state["actorWhy"]), (actor, why))

    def test_cross_site_and_same_site_are_refused_on_every_api_get(self):
        self.browser.open()
        for path in ("/api/state", "/api/tools", "/api/calls", "/api/message/out_001-d1.txt"):
            for label in ("same-site", "cross-site", "elsewhere"):
                with self.subTest(path=path, label=label):
                    sent = {"Cookie": self.browser.cookie, "Sec-Fetch-Site": label}
                    reply = self.call("GET", path, headers=sent)
                    self.assertEqual((reply.status, reply.json["outcome"]), (403, "cross_site"))

    def test_only_the_organiser_is_shown_the_agent_address_and_the_member_links(self):
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        organiser = self.browser.state()
        self.assertEqual(organiser["actor"], "person")
        self.assertRegex(organiser["agentAddress"], r"^http://127\.0\.0\.1:\d+/agent/[0-9a-f]{32}$")
        links = organiser["memberLinks"]["out_001"]
        self.assertEqual(sorted(links), ["m1", "m2", "m3", "m4"])
        self.assertTrue(all(re.search(r"/m/[0-9a-f]{32}$", link) for link in links.values()))
        for extra in ({}, {"Sec-Fetch-Site": "none"}, {"X-Common-Ground-As": "agent"}):
            with self.subTest(extra):
                reply = self.call("GET", "/api/state", headers={"Cookie": self.browser.cookie, **extra})
                self.assertNotIn("agentAddress", reply.json)
                self.assertNotIn("memberLinks", reply.json)

    def test_no_view_holds_the_cookie_id_or_a_token_apart_from_the_two_it_hands_the_organiser(self):
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        ws = self.browser.workspace
        secrets = [ws["id"], ws["agentToken"]] + [m["token"] for m in ws["outings"][0]["members"]]
        views = {
            "agent state": self.call("GET", "/api/state", headers={"Cookie": self.browser.cookie}).text,
            "tools": self.browser.get("/api/tools").text,
            "calls": self.browser.get("/api/calls").text,
            "organiser state, minus the links": json.dumps(
                {k: v for k, v in self.browser.state().items() if k not in ("agentAddress", "memberLinks")}
            ),
        }
        for name, text in views.items():
            for secret in secrets:
                with self.subTest(view=name, secret=secret[:8]):
                    self.assertNotIn(secret, text)
        organiser = self.browser.get("/api/state").text
        self.assertNotIn(ws["id"], organiser)
        self.assertNotIn('"token"', organiser)
        self.assertIsNone(WORKSPACE_ID.search(organiser))

    def test_the_state_reports_the_mode_the_allowances_and_the_limiter_key(self):
        self.browser.open()
        state = self.browser.state()
        self.assertEqual(state["mode"], {"source": "fake", "key": "missing", "ceilingSpent": False,
                                         "newOutingsSynthetic": False, "shapesVerified": False})
        self.assertEqual(state["limiterKey"], "peer")
        self.assertEqual(state["allowances"]["agentAllowance"], 48)
        self.assertEqual(state["callLimit"], {"default": 30, "max": 60})
        self.assertEqual(state["outings"], [])

    def test_the_tools_route_lists_the_registry_and_no_verb(self):
        self.browser.open()
        tools = self.browser.get("/api/tools").json["tools"]
        self.assertEqual(tools, agent_tools.listing())
        self.assertFalse({t["name"] for t in tools} & set(VERBS))

    def test_the_calls_route_shows_only_this_workspaces_calls_by_label(self):
        first, second = Browser(self.served), Browser(self.served)
        sample_walk(first, compare=False)
        second.open()
        second.ok("open_outing", sample_args())
        self.assertEqual(second.get("/api/calls").json["calls"], [])
        calls = first.get("/api/calls").json["calls"]
        self.assertEqual(len(calls), 9)
        self.assertTrue(all(c["workspace"] == outings.ledger_label(first.workspace["id"]) for c in calls))

    def test_a_released_message_is_text_and_a_draft_is_404(self):
        sample_walk(self.browser)
        outing = self.browser.state()["outings"][-1]
        pick = outing["places"][0]["entityId"]
        asked = {"outing_id": "out_001", "place_id": pick, "kind": "invitation"}
        draft = self.browser.ok("write_draft", asked)
        self.assertEqual(self.browser.get(f"/api/message/out_001-{draft['draftId']}.txt").status, 404)
        revision = self.browser.state()["outings"][-1]["revision"]
        self.browser.ok("sign_off_message", {"outing_id": "out_001", "draft_id": draft["draftId"],
                                             "sender_name": "Noor", "revision": revision})
        reply = self.browser.get(f"/api/message/out_001-{draft['draftId']}.txt")
        self.assertEqual(reply.status, 200)
        self.assertTrue(reply.headers["content-type"].startswith("text/plain"))
        self.assertNotIn("DRAFT", reply.text)
        self.assertTrue(reply.text.rstrip().endswith("Noor"))
        self.assertEqual(self.browser.get("/api/message/out_001-d9.txt").status, 404)
        self.assertEqual(self.browser.get("/api/message/out_009-d1.txt").status, 404)

    def test_a_restart_forgets_every_workspace(self):
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        other = Served()
        with other:
            reply = other.call("GET", "/api/state", headers={"Cookie": self.browser.cookie,
                                                              "Sec-Fetch-Site": "same-origin"})
            self.assertEqual((reply.status, reply.json["outcome"]), (401, "no_workspace"))
            fresh = other.call("GET", "/", headers={"Cookie": self.browser.cookie})
            self.assertIn("cg_w=ws_", fresh.headers["set-cookie"])


class Dispatch(Routes):
    def setUp(self):
        super().setUp()
        self.browser.open()

    def test_a_same_origin_post_with_the_cookie_is_the_organiser(self):
        answer = self.browser.act("open_outing", sample_args())
        self.assertTrue(answer["ok"])
        self.assertTrue(all("link" in m for m in answer["result"]["members"]))
        log = self.browser.workspace["activityLog"]
        self.assertEqual((log[-1]["actor"], log[-1]["as"]), ("person", "organiser"))

    def test_a_cookie_without_the_label_is_the_agent_not_an_error(self):
        sent = {"Cookie": self.browser.cookie, "Origin": self.served.origin}
        opening = {"tool": "open_outing", "args": sample_args()}
        answer = self.call("POST", "/api/dispatch", opening, headers=sent)
        self.assertEqual(answer.status, 200)
        self.assertTrue(all("link" not in m for m in answer.json["result"]["members"]))
        refused = self.call("POST", "/api/dispatch", {"tool": "pick_place", "args": {}}, headers=sent)
        self.assertEqual((refused.status, refused.json["outcome"]), (200, "not_a_tool"))

    def test_none_and_the_agent_header_make_the_agent_too(self):
        spoken = {"Sec-Fetch-Site": "same-origin", "X-Common-Ground-As": "agent"}
        for extra in ({"Sec-Fetch-Site": "none"}, spoken):
            with self.subTest(extra):
                answer = self.browser.act("resolve_match", {}, **extra)
                self.assertEqual(answer["outcome"], "not_a_tool")

    def test_the_actor_never_comes_from_the_body(self):
        reply = self.browser.post("/api/dispatch", {"tool": "spend_report", "args": {}, "actor": "person"})
        self.assertEqual((reply.status, reply.json["outcome"]), (400, "bad_request"))

    def test_cross_site_and_same_site_posts_are_refused(self):
        for label in ("cross-site", "same-site"):
            reply = self.call("POST", "/api/dispatch", {"tool": "spend_report"}, headers={
                "Cookie": self.browser.cookie, "Sec-Fetch-Site": label, "Origin": self.served.origin})
            self.assertEqual((reply.status, reply.json["outcome"]), (403, "cross_site"))

    def test_a_foreign_origin_is_refused_even_with_the_right_label(self):
        secure = "https://" + self.served.host
        for origin in ("https://elsewhere.example", "null", "http://127.0.0.1:1", secure):
            with self.subTest(origin):
                reply = self.call("POST", "/api/dispatch", {"tool": "spend_report"}, headers={
                    "Cookie": self.browser.cookie, "Sec-Fetch-Site": "same-origin", "Origin": origin})
                self.assertEqual((reply.status, reply.json["outcome"]), (403, "bad_origin"))

    def test_a_post_with_no_origin_header_is_allowed(self):
        reply = self.call("POST", "/api/dispatch", {"tool": "spend_report"}, headers={
            "Cookie": self.browser.cookie, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(reply.status, 200)

    def test_x_forwarded_proto_is_ignored_in_working_out_the_servers_own_origin(self):
        reply = self.call("POST", "/api/dispatch", {"tool": "spend_report"}, headers={
            **person_headers(self.served), "Cookie": self.browser.cookie, "X-Forwarded-Proto": "https",
            "Origin": "https://" + self.served.host})
        self.assertEqual((reply.status, reply.json["outcome"]), (403, "bad_origin"))

    def test_plain_http_at_a_public_name_is_refused_because_the_servers_origin_is_https(self):
        s = Served(allowed_hosts=("127.0.0.1", "localhost", "[::1]", "demo.example"))
        with s:
            hello = s.call("GET", "/", host="demo.example")
            cookie = hello.headers["set-cookie"].split(";")[0]
            sent = {"Cookie": cookie, "Sec-Fetch-Site": "same-origin"}
            plain = s.call("POST", "/api/dispatch", {"tool": "spend_report"}, host="demo.example",
                           headers={**sent, "Origin": "http://demo.example"})
            self.assertEqual((plain.status, plain.json["outcome"]), (403, "bad_origin"))
            secure = s.call("POST", "/api/dispatch", {"tool": "spend_report"}, host="demo.example",
                            headers={**sent, "Origin": "https://demo.example"})
            self.assertEqual(secure.status, 200)

    def test_the_body_must_be_json_and_small_and_shaped(self):
        sent = person_headers(self.served) | {"Cookie": self.browser.cookie}
        kinds = [("text/plain", 415), ("application/x-www-form-urlencoded", 415),
                 ("application/json; charset=utf-8", 200)]
        for kind, status in kinds:
            with self.subTest(kind):
                reply = self.call("POST", "/api/dispatch", raw=b'{"tool":"spend_report"}',
                                  headers={**sent, "Content-Type": kind})
                self.assertEqual(reply.status, status)
        malformed = (b"{", b"[]", b'"x"', b'{"tool": 1}', b'{"args": {}}',
                     b'{"tool": "spend_report", "x": 1}')
        for raw in malformed:
            with self.subTest(raw):
                self.assertEqual(self.call("POST", "/api/dispatch", raw=raw, headers=sent).status, 400)
        too_big = b'{"tool":"spend_report","args":{"x":"' + b"a" * web.MAX_BODY + b'"}}'
        reply = self.call("POST", "/api/dispatch", raw=too_big, headers=sent)
        self.assertEqual((reply.status, reply.json["outcome"]), (413, "body_too_large"))
        exactly = b'{"tool":"spend_report"}'.ljust(web.MAX_BODY)
        self.assertEqual(self.call("POST", "/api/dispatch", raw=exactly, headers=sent).status, 200)

    def test_a_declared_length_far_over_the_limit_is_refused_without_reading_it(self):
        with socket.create_connection(("127.0.0.1", self.served.port), timeout=10) as raw:
            raw.sendall(("POST /api/dispatch HTTP/1.1\r\nHost: " + self.served.host
                         + "\r\nContent-Type: application/json\r\nContent-Length: 50000000\r\n\r\n").encode())
            head = raw.recv(4096).decode()
        self.assertTrue(head.startswith("HTTP/1.0 413"), head)

    def test_a_chunked_body_or_a_bad_length_is_refused(self):
        for line in ("Transfer-Encoding: chunked", "Content-Length: -1", "Content-Length: abc"):
            with self.subTest(line):
                with socket.create_connection(("127.0.0.1", self.served.port), timeout=10) as raw:
                    raw.sendall(("POST /api/dispatch HTTP/1.1\r\nHost: " + self.served.host
                                 + "\r\n" + line + "\r\n\r\n").encode())
                    head = raw.recv(4096).decode()
                self.assertTrue(head.startswith("HTTP/1.0 411"), head)

    def test_the_wrong_method_names_what_is_allowed(self):
        for path, allowed in (("/api/dispatch", "POST"), ("/api/state", "GET")):
            wrong = "GET" if allowed == "POST" else "POST"
            reply = self.browser.post(path, {}) if wrong == "POST" else self.browser.get(path)
            self.assertEqual((reply.status, reply.headers["allow"]), (405, allowed))

    def test_a_refusal_from_the_gateway_is_a_200_with_ok_false(self):
        answer = self.browser.act("show_evidence", {"outing_id": "out_001", "place_id": "x"})
        self.assertEqual((answer["ok"], answer["outcome"]), (False, "unknown_outing"))
        self.assertEqual(answer["error"]["code"], "unknown_outing")


class Members(Routes):
    def setUp(self):
        super().setUp()
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        for member in self.browser.state()["outings"][0]["members"]:
            for favourite in member["favourites"]:
                self.browser.ok("look_up_favourite", {
                    "outing_id": "out_001", "member_id": member["id"], "favourite_id": favourite["id"]})
        links = self.browser.state()["memberLinks"]["out_001"]
        self.token = {m: links[m].rsplit("/", 1)[1] for m in links}
        self.stranger = Browser(self.served, labelled=True)
        self.candidates = {
            f["id"]: f["candidates"][0]["entityId"]
            for m in self.browser.state()["outings"][0]["members"] for f in m["favourites"]
        }

    def member_get(self, member):
        path = f"/api/member/{self.token[member]}/state"
        return self.call("GET", path, headers={"Sec-Fetch-Site": "same-origin"})

    def member_post(self, member, tool, args, **extra):
        sent = {"Sec-Fetch-Site": "same-origin", "Origin": self.served.origin, **extra}
        return self.call("POST", f"/api/member/{self.token[member]}/dispatch", {"tool": tool, "args": args},
                         headers=sent)

    def test_a_members_view_holds_only_their_own_favourites(self):
        reply = self.member_get("m2")
        view = reply.json
        self.assertEqual((view["actor"], view["actorWhy"]), ("person", "same_origin"))
        self.assertEqual(view["member"]["name"], "Owen")
        self.assertEqual(sorted(f["id"] for f in view["member"]["favourites"]), ["f3", "f4"])
        text = reply.text
        for other in ("Noor", "Pia", "Quinn"):
            self.assertNotIn(other, text)
        for token in self.token.values():
            self.assertNotIn(token, text)
        self.assertTrue(view["member"]["favourites"][0]["candidates"])

    def test_the_members_link_with_the_label_resolves_their_own_favourite_as_theirs(self):
        reply = self.member_post("m2", "resolve_match", {
            "outing_id": "out_001", "member_id": "m2", "favourite_id": "f3",
            "entity_id": self.candidates["f3"]})
        self.assertEqual((reply.status, reply.json["ok"]), (200, True))
        self.assertEqual(reply.json["result"]["resolvedBy"], "member")
        self.assertEqual(self.browser.workspace["activityLog"][-1]["as"], "member:m2")

    def test_a_members_link_cannot_resolve_for_anyone_else_or_run_another_verb(self):
        other = self.member_post("m2", "resolve_match", {
            "outing_id": "out_001", "member_id": "m3", "favourite_id": "f5",
            "entity_id": self.candidates["f5"]})
        self.assertEqual(other.json["outcome"], "wrong_member")
        for verb in ("pick_place", "change_conditions", "sign_off_message", "lift_call_limit",
                     "rule_out_place"):
            with self.subTest(verb):
                self.assertEqual(self.member_post("m2", verb, {"outing_id": "out_001"}).json["outcome"],
                                 "wrong_actor")
        self.assertEqual(self.member_post("m2", "run_comparison", {"outing_id": "out_001"}).json["outcome"],
                         "wrong_actor")

    def test_without_the_label_a_members_link_is_the_agent_and_resolves_nothing(self):
        args = {"outing_id": "out_001", "member_id": "m2", "favourite_id": "f3",
                "entity_id": self.candidates["f3"]}
        for extra in ({"Sec-Fetch-Site": "none"}, {"X-Common-Ground-As": "agent"}):
            with self.subTest(extra):
                reply = self.member_post("m2", "resolve_match", args, **extra)
                self.assertEqual(reply.json["outcome"], "not_a_tool")
        bare = self.call("POST", f"/api/member/{self.token['m2']}/dispatch",
                         {"tool": "resolve_match", "args": args}, headers={"Origin": self.served.origin})
        self.assertEqual(bare.json["outcome"], "not_a_tool")
        state = self.call("GET", f"/api/member/{self.token['m2']}/state").json
        self.assertEqual((state["actor"], state["actorWhy"]), ("agent", "no_fetch_metadata"))
        self.assertIsNone(self.browser.state()["outings"][0]["members"][1]["favourites"][0]["resolved"])

    def test_cross_site_and_foreign_origin_are_refused_and_an_unknown_token_is_404(self):
        base = {"tool": "spend_report"}
        cross = self.call("POST", f"/api/member/{self.token['m2']}/dispatch", base,
                          headers={"Sec-Fetch-Site": "cross-site", "Origin": self.served.origin})
        self.assertEqual(cross.json["outcome"], "cross_site")
        foreign = self.call("POST", f"/api/member/{self.token['m2']}/dispatch", base,
                            headers={"Sec-Fetch-Site": "same-origin", "Origin": "https://elsewhere.example"})
        self.assertEqual(foreign.json["outcome"], "bad_origin")
        self.assertEqual(self.call("GET", "/api/member/nope/state").status, 404)
        self.assertEqual(self.call("POST", "/api/member/nope/dispatch", base).status, 404)
        self.assertEqual(self.call("GET", f"/api/member/{self.token['m2']}/elsewhere").status, 404)

    def test_a_members_requests_need_no_cookie(self):
        self.assertEqual(self.member_get("m3").status, 200)


class AgentAddress(Routes):
    def setUp(self):
        super().setUp()
        self.browser.open()
        self.token = self.browser.state()["agentAddress"].rsplit("/", 1)[1]
        self.base = f"/agent/{self.token}"

    def test_tools_lists_the_registry_and_no_verb(self):
        tools = self.call("GET", f"{self.base}/tools").json["tools"]
        self.assertEqual(tools, agent_tools.listing())
        self.assertFalse({t["name"] for t in tools} & set(VERBS))

    def test_dispatch_is_always_the_agent_even_with_the_cookie_and_the_label(self):
        sent = {"Cookie": self.browser.cookie, **person_headers(self.served)}
        opened = self.call("POST", f"{self.base}/dispatch", {"tool": "open_outing", "args": sample_args()},
                           headers=sent)
        self.assertTrue(all("link" not in m for m in opened.json["result"]["members"]))
        for verb in VERBS:
            with self.subTest(verb):
                self.assertEqual(self.call("POST", f"{self.base}/dispatch", {"tool": verb, "args": {}},
                                           headers=sent).json["outcome"], "not_a_tool")
        self.assertEqual({e["actor"] for e in self.browser.workspace["activityLog"]}, {"agent"})

    def test_the_label_is_ignored_here_so_a_cross_site_script_can_hold_the_token_alone(self):
        reply = self.call("POST", f"{self.base}/dispatch", {"tool": "spend_report"},
                          headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual((reply.status, reply.json["ok"]), (200, True))

    def test_it_reaches_one_workspace_only(self):
        other = Browser(self.served)
        other.open()
        opened = self.call("POST", f"{self.base}/dispatch", {"tool": "open_outing", "args": sample_args()})
        self.assertTrue(opened.json["ok"])
        self.assertEqual(len(self.browser.state()["outings"]), 1)
        self.assertEqual(other.state()["outings"], [])
        reach = self.call("POST", f"{self.base}/dispatch",
                          {"tool": "read_outing", "args": {"outing_id": "out_002"}})
        self.assertEqual(reach.json["outcome"], "unknown_outing")

    def test_an_unknown_token_or_action_is_404_and_the_wrong_method_is_405(self):
        self.assertEqual(self.call("GET", "/agent/not-a-token/tools").status, 404)
        stranger = self.call("POST", "/agent/not-a-token/dispatch", {"tool": "spend_report"})
        self.assertEqual(stranger.status, 404)
        self.assertEqual(self.call("GET", f"{self.base}/elsewhere").status, 404)
        self.assertEqual(self.call("POST", f"{self.base}/tools", {}).status, 405)
        self.assertEqual(self.call("GET", f"{self.base}/dispatch").status, 405)

    def test_a_foreign_origin_content_type_and_size_are_refused(self):
        body = {"tool": "spend_report"}
        foreign = self.call("POST", f"{self.base}/dispatch", body,
                            headers={"Origin": "https://elsewhere.example"})
        self.assertEqual(foreign.json["outcome"], "bad_origin")
        self.assertEqual(self.call("POST", f"{self.base}/dispatch", raw=b"{}",
                                   headers={"Content-Type": "text/plain"}).status, 415)
        big = self.call("POST", f"{self.base}/dispatch", raw=b" " * (web.MAX_BODY + 1))
        self.assertEqual(big.status, 413)


class Limits(Routes):
    def test_each_dispatch_route_allows_thirty_a_minute_per_workspace(self):
        self.browser.open()
        statuses = [self.browser.post("/api/dispatch", {"tool": "spend_report"}).status for _ in range(31)]
        self.assertEqual(statuses, [200] * 30 + [429])
        late = self.browser.post("/api/dispatch", {"tool": "spend_report"})
        self.assertEqual(late.json["outcome"], "rate_limited")
        self.assertGreaterEqual(int(late.headers["retry-after"]), 1)
        self.assertEqual(self.browser.get("/api/state").status, 200)

    def test_the_window_slides(self):
        self.browser.open()
        for _ in range(30):
            self.browser.post("/api/dispatch", {"tool": "spend_report"})
        self.assertEqual(self.browser.post("/api/dispatch", {"tool": "spend_report"}).status, 429)
        self.served.session.clock.now += 61
        self.assertEqual(self.browser.post("/api/dispatch", {"tool": "spend_report"}).status, 200)

    def test_the_limit_is_per_workspace_and_never_per_client_address(self):
        one, two = Browser(self.served), Browser(self.served)
        one.open()
        two.open()
        for _ in range(30):
            self.assertEqual(one.post("/api/dispatch", {"tool": "spend_report"}).status, 200)
        self.assertEqual(one.post("/api/dispatch", {"tool": "spend_report"}).status, 429)
        for _ in range(30):
            self.assertEqual(two.post("/api/dispatch", {"tool": "spend_report"}).status, 200)

    def test_the_organisers_members_and_the_agents_have_separate_buckets(self):
        self.browser.open()
        self.browser.ok("open_outing", sample_args())
        links = self.browser.state()["memberLinks"]["out_001"]
        token = links["m2"].rsplit("/", 1)[1]
        agent = self.browser.state()["agentAddress"].rsplit("/", 1)[1]
        for _ in range(30):
            self.browser.post("/api/dispatch", {"tool": "spend_report"})
        mine = {"Sec-Fetch-Site": "same-origin", "Origin": self.served.origin}
        self.assertEqual(self.browser.post("/api/dispatch", {"tool": "spend_report"}).status, 429)
        ok = self.call("POST", f"/api/member/{token}/dispatch", {"tool": "spend_report"}, headers=mine)
        self.assertEqual(ok.status, 200)
        self.assertEqual(self.call("POST", f"/agent/{agent}/dispatch", {"tool": "spend_report"}).status, 200)

    def test_creating_workspaces_is_limited_per_client_key(self):
        statuses = [self.call("GET", "/").status for _ in range(31)]
        self.assertEqual(statuses, [200] * 30 + [429])
        self.assertIn("retry-after", self.call("GET", "/").headers)
        self.assertEqual(self.call("GET", "/app.js").status, 200)

    def test_a_visit_that_already_has_a_workspace_does_not_count(self):
        self.browser.open()
        for _ in range(40):
            self.assertEqual(self.call("GET", "/", headers={"Cookie": self.browser.cookie}).status, 200)

    def test_creating_is_limited_in_all_whatever_the_clients(self):
        s = Served(trust_proxy=True)
        with s:
            statuses = []
            for n in range(125):
                client = f"10.0.{n // 30}.{n % 30}"
                statuses.append(s.call("GET", "/", headers={"X-Forwarded-For": client}).status)
            self.assertEqual(statuses[:120], [200] * 120)
            self.assertEqual(statuses[120:], [429] * 5)

    def test_the_client_key_is_the_peer_or_the_right_most_forwarded_value(self):
        peer = Served()
        with peer:
            statuses = [peer.call("GET", "/", headers={"X-Forwarded-For": f"10.1.1.{n}"}).status
                        for n in range(31)]
            self.assertEqual(statuses[-1], 429)
            b = Browser(peer)
            self.assertEqual(b.open().status, 429)
        proxied = Served(trust_proxy=True)
        with proxied:
            statuses = [proxied.call("GET", "/", headers={"X-Forwarded-For": f"9.9.9.9, 10.1.1.{n}"}).status
                        for n in range(31)]
            self.assertEqual(statuses, [200] * 31)
            b = Browser(proxied)
            b.open(), b.ok("open_outing", sample_args())
            via = b.get("/api/state", **{"X-Forwarded-For": "1.2.3.4"}).json
            self.assertEqual(via["limiterKey"], "forwarded")
            bare = b.get("/api/state").json
            self.assertEqual(bare["limiterKey"], "peer")


class Mistakes(Routes):
    def test_an_internal_error_is_a_500_with_a_name_and_no_detail(self):
        self.browser.open()
        original = self.served.app._state
        self.served.app._state = lambda *a: (_ for _ in ()).throw(RuntimeError("secret detail"))
        self.addCleanup(setattr, self.served.app, "_state", original)
        with contextlib.redirect_stderr(io.StringIO()) as noise:
            reply = self.browser.get("/api/state")
        self.assertEqual((reply.status, reply.json["outcome"]), (500, "internal"))
        self.assertNotIn("secret", reply.text)
        self.assertEqual(noise.getvalue(), "common_ground: internal error (RuntimeError)\n")
        self.assertEqual(self.call("GET", "/healthz").status, 200)


if __name__ == "__main__":
    unittest.main()
