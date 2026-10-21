"""The hosted MCP endpoint, case by case: one path, two protocol eras. Pure cases call `mcp_http.respond`
with headers and a body; the cases that need a socket (GET and DELETE, the door's guards, a cookie that
upgrades nothing) are in HttpEndpoint, further down."""
import base64
import json
import unittest

from common_ground import agent_tools, mcp_http, person_verbs
from tests.served import Browser, Served
from tests.session import Session
from tests.test_outings import sample_args

MODERN = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": MODERN,
    "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}
ACCEPT = "application/json, text/event-stream"
VERBS = sorted(person_verbs.VERBS)


def headers(method=None, name=None, version=MODERN, **extra):
    sent = {"accept": ACCEPT, "content-type": "application/json"}
    if version:
        sent["mcp-protocol-version"] = version
    if method:
        sent["mcp-method"] = method
    if name:
        sent["mcp-name"] = name
    return {**sent, **extra}


def body(method, params=None, id=1, meta=True):
    message = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None or meta:
        message["params"] = {**(params or {}), **({"_meta": META} if meta else {})}
    return json.dumps(message).encode()


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.gateway, self.ws = self.s.gateway, self.s.ws

    def post(self, raw, **sent):
        status, payload = mcp_http.respond(self.gateway, self.ws, sent or headers(), raw)
        return status, payload

    def modern(self, method, params=None, name=None, **extra):
        return self.post(body(method, params), **headers(method, name, **extra))

    def legacy(self, method, params=None, version="2025-11-25", id=2):
        message = {"jsonrpc": "2.0", "id": id, "method": method}
        if params is not None:
            message["params"] = params
        return self.post(json.dumps(message).encode(), **headers(version=version))

    def assertRpcError(self, answer, status, code):
        self.assertEqual(answer[0], status)
        self.assertEqual(answer[1]["error"]["code"], code, answer[1])
        self.assertNotIn("result", answer[1])


class Modern(Endpoint):
    def test_discover_names_every_revision_served_and_declares_only_tools(self):
        status, payload = self.modern("server/discover")
        result = payload["result"]
        self.assertEqual(status, 200)
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["supportedVersions"], ["2026-07-28", "2025-11-25", "2025-06-18"])
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "common-ground")
        self.assertIn("instructions", result)
        self.assertEqual(payload["id"], 1)

    def test_the_instructions_name_no_verb_and_say_what_is_left_to_people(self):
        text = mcp_http.INSTRUCTIONS
        for verb in VERBS:
            self.assertNotIn(verb, text)
        self.assertIn("people's decisions", text)

    def test_tools_list_is_the_registry_and_nothing_else(self):
        status, payload = self.modern("tools/list")
        names = [t["name"] for t in payload["result"]["tools"]]
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["tools"], agent_tools.listing())
        self.assertEqual(names, list(agent_tools.TOOLS))
        self.assertEqual(len(names), 8)
        self.assertFalse(set(names) & set(VERBS))
        self.assertEqual(payload["result"]["resultType"], "complete")

    def test_tools_call_of_a_listed_tool_runs_through_dispatch_as_the_agent(self):
        args = sample_args()
        status, payload = self.modern("tools/call", {"name": "open_outing", "arguments": args}, "open_outing")
        result = payload["result"]
        self.assertEqual(status, 200)
        self.assertFalse(result["isError"])
        self.assertEqual(result["resultType"], "complete")
        opened = json.loads(result["content"][0]["text"])
        self.assertEqual(opened, result["structuredContent"])
        self.assertEqual(opened["outingId"], "out_001")
        self.assertTrue(all("link" not in m for m in opened["members"]))
        self.assertEqual(self.s.outing()["members"][0]["name"], args["members"][0]["name"])
        self.assertEqual(self.s.gateway.document["workspaces"][0]["activityLog"][-1]["actor"], "agent")

    def test_a_human_verb_is_an_unknown_tool_with_not_a_tool_in_its_data(self):
        for verb in VERBS:
            with self.subTest(verb):
                answer = self.modern("tools/call", {"name": verb, "arguments": {}}, verb)
                self.assertRpcError(answer, 400, mcp_http.INVALID_PARAMS)
                self.assertEqual(answer[1]["error"]["data"], {"outcome": "not_a_tool"})
                self.assertIn(verb, answer[1]["error"]["message"])

    def test_an_unknown_name_is_the_same_error(self):
        answer = self.modern("tools/call", {"name": "book_a_table", "arguments": {}}, "book_a_table")
        self.assertRpcError(answer, 400, mcp_http.INVALID_PARAMS)
        self.assertEqual(answer[1]["error"]["data"]["outcome"], "not_a_tool")

    def test_a_refusal_for_a_listed_tool_is_a_result_with_is_error(self):
        cases = [
            ("look_up_kind", {"outing_id": "out_009", "query": "restaurant"}, "unknown_outing"),
            ("show_evidence", {"outing_id": "out_009", "place_id": "x", "kind": "y"}, "smuggled_field"),
            ("run_comparison", {}, "bad_arguments"),
        ]
        for name, arguments, outcome in cases:
            with self.subTest(outcome):
                status, payload = self.modern("tools/call", {"name": name, "arguments": arguments}, name)
                result = payload["result"]
                self.assertEqual(status, 200)
                self.assertTrue(result["isError"])
                self.assertEqual(json.loads(result["content"][0]["text"])["outcome"], outcome)
                self.assertNotIn("error", payload)

    def test_the_call_limit_and_the_allowance_arrive_as_is_error_too(self):
        s = Session(call_limit=1)
        outing = s.ok("open_outing", sample_args())["outingId"]
        asked = {"outing_id": outing, "member_id": "m1", "favourite_id": "f1"}
        first = mcp_http.respond(s.gateway, s.ws, headers("tools/call", "look_up_favourite"),
                                 body("tools/call", {"name": "look_up_favourite", "arguments": asked}))
        second = mcp_http.respond(s.gateway, s.ws, headers("tools/call", "look_up_favourite"),
                                  body("tools/call", {"name": "look_up_favourite", "arguments": asked}))
        self.assertFalse(first[1]["result"]["isError"])
        self.assertTrue(second[1]["result"]["isError"])
        self.assertIn("over_limit", second[1]["result"]["content"][0]["text"])

    def test_the_version_header_and_the_metadata_must_agree(self):
        answer = self.post(body("tools/list"), **headers("tools/list", version="2025-11-25"))
        self.assertRpcError(answer, 400, mcp_http.HEADER_MISMATCH)
        answer = self.post(body("tools/list"), **headers("tools/list", version=None))
        self.assertRpcError(answer, 400, mcp_http.HEADER_MISMATCH)

    def test_the_method_header_is_required_and_must_match(self):
        wrong = self.post(body("tools/list"), **headers("tools/call"))
        self.assertRpcError(wrong, 400, mcp_http.HEADER_MISMATCH)
        self.assertRpcError(self.post(body("tools/list"), **headers()), 400, mcp_http.HEADER_MISMATCH)

    def test_the_name_header_is_required_for_a_call_and_must_match(self):
        params = {"name": "spend_report", "arguments": {}}
        for sent in (None, "read_outing"):
            with self.subTest(sent):
                answer = self.post(body("tools/call", params), **headers("tools/call", sent))
                self.assertRpcError(answer, 400, mcp_http.HEADER_MISMATCH)
        ok = self.post(body("tools/call", params), **headers("tools/call", "spend_report"))
        self.assertEqual(ok[0], 200)

    def test_the_name_header_may_carry_the_base64_form(self):
        encoded = "=?base64?" + base64.b64encode(b"spend_report").decode() + "?="
        answer = self.post(body("tools/call", {"name": "spend_report", "arguments": {}}),
                           **headers("tools/call", encoded))
        self.assertEqual(answer[0], 200)
        broken = self.post(body("tools/call", {"name": "spend_report", "arguments": {}}),
                           **headers("tools/call", "=?base64?!!!?="))
        self.assertRpcError(broken, 400, mcp_http.HEADER_MISMATCH)

    def test_an_unsupported_version_lists_what_is_supported(self):
        meta = {**META, "io.modelcontextprotocol/protocolVersion": "1900-01-01"}
        message = {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {"_meta": meta}}
        raw = json.dumps(message).encode()
        status, payload = self.post(raw, **headers("tools/list", version="1900-01-01"))
        self.assertEqual((status, payload["id"], payload["error"]["code"]), (400, 5, -32022))
        self.assertEqual(payload["error"]["data"]["supported"], ["2026-07-28", "2025-11-25", "2025-06-18"])
        self.assertEqual(payload["error"]["data"]["requested"], "1900-01-01")

    def test_a_legacy_version_in_modern_clothes_is_unsupported_too(self):
        meta = {**META, "io.modelcontextprotocol/protocolVersion": "2025-11-25"}
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}
        raw = json.dumps(message).encode()
        self.assertRpcError(self.post(raw, **headers("tools/list", version="2025-11-25")), 400, -32022)

    def test_missing_required_metadata_is_invalid_params(self):
        no_version = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                                 "params": {"_meta": {}}}).encode()
        self.assertRpcError(self.post(no_version, **headers("tools/list")), 400, mcp_http.INVALID_PARAMS)
        no_meta = body("tools/list", meta=False)
        self.assertRpcError(self.post(no_meta, **headers("tools/list")), 400, mcp_http.INVALID_PARAMS)
        no_caps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {
            "io.modelcontextprotocol/protocolVersion": MODERN}}}).encode()
        self.assertRpcError(self.post(no_caps, **headers("tools/list")), 400, mcp_http.INVALID_PARAMS)

    def test_an_unknown_method_is_404_with_method_not_found(self):
        for method in ("ping", "resources/list", "prompts/list", "subscriptions/listen", "tools/frobnicate"):
            with self.subTest(method):
                self.assertRpcError(self.modern(method), 404, mcp_http.METHOD_NOT_FOUND)

    def test_there_is_no_handshake_and_no_session_in_this_era(self):
        status, payload = self.modern("tools/list")
        self.assertNotIn("Mcp-Session-Id", json.dumps(payload))
        self.assertNotIn("sessionId", json.dumps(payload))

    def test_a_stray_session_header_is_ignored(self):
        answer = self.post(body("tools/list"), **headers("tools/list", **{"mcp-session-id": "abc"}))
        self.assertEqual(answer[0], 200)

    def test_an_accept_header_that_misses_a_type_is_refused(self):
        for accept in ("application/json", "text/event-stream", "", "text/html"):
            with self.subTest(accept):
                answer = self.post(body("tools/list"), **headers("tools/list", accept=accept))
                self.assertRpcError(answer, 406, mcp_http.INVALID_REQUEST)
        for accept in ("*/*", "application/*, text/*", "application/json;q=0.9, text/event-stream"):
            with self.subTest(accept):
                answer = self.post(body("tools/list"), **headers("tools/list", accept=accept))
                self.assertEqual(answer[0], 200)

    def test_malformed_bodies_are_named(self):
        self.assertRpcError(self.post(b"{nope", **headers()), 400, mcp_http.PARSE_ERROR)
        self.assertRpcError(self.post(b"\xff\xfe", **headers()), 400, mcp_http.PARSE_ERROR)
        self.assertRpcError(self.post(b"[1,2]", **headers()), 400, mcp_http.INVALID_REQUEST)
        self.assertRpcError(self.post(b'"hi"', **headers()), 400, mcp_http.INVALID_REQUEST)
        self.assertRpcError(self.post(b'{"jsonrpc":"1.0","id":1,"method":"x"}', **headers()), 400, -32600)
        self.assertRpcError(self.post(b'{"jsonrpc":"2.0","id":true,"method":"x"}', **headers()), 400, -32600)
        self.assertRpcError(self.post(b'{"jsonrpc":"2.0","id":1,"result":{}}', **headers()), 400, -32600)

    def test_the_arguments_of_a_call_must_be_an_object(self):
        raw = body("tools/call", {"name": "spend_report", "arguments": [1]})
        self.assertRpcError(self.post(raw, **headers("tools/call", "spend_report")), 400, -32602)
        raw = body("tools/call", {"name": 7, "arguments": {}})
        self.assertRpcError(self.post(raw, **headers("tools/call", "7")), 400, -32602)

    def test_an_ordinary_notification_is_accepted_and_an_odd_one_is_not(self):
        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}).encode()
        self.assertEqual(self.post(raw, **headers()), (202, None))
        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/elsewhere"}).encode()
        status, payload = self.post(raw, **headers())
        self.assertEqual((status, payload["error"]["code"], payload["id"]), (404, -32601, None))

    def test_the_id_comes_back_as_sent(self):
        for sent in ("abc", 41):
            with self.subTest(sent):
                raw = json.dumps({"jsonrpc": "2.0", "id": sent, "method": "tools/list",
                                  "params": {"_meta": META}}).encode()
                self.assertEqual(self.post(raw, **headers("tools/list"))[1]["id"], sent)


class Legacy(Endpoint):
    def initialize(self, version):
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"},
        }}).encode()
        return self.post(raw, accept=ACCEPT)

    def test_initialize_answers_with_the_version_asked_when_it_is_served(self):
        for version in ("2025-11-25", "2025-06-18"):
            with self.subTest(version):
                status, payload = self.initialize(version)
                result = payload["result"]
                self.assertEqual(status, 200)
                self.assertEqual(result["protocolVersion"], version)
                self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
                self.assertEqual(result["serverInfo"]["name"], "common-ground")
                self.assertNotIn("resultType", result)
                self.assertNotIn("session", json.dumps(result).lower())

    def test_initialize_answers_with_the_newest_legacy_version_to_any_other_ask(self):
        for version in ("2025-03-26", "2024-11-05", "2099-01-01"):
            with self.subTest(version):
                self.assertEqual(self.initialize(version)[1]["result"]["protocolVersion"], "2025-11-25")

    def test_initialize_needs_a_version(self):
        raw = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
        self.assertRpcError(self.post(raw, accept=ACCEPT), 200, mcp_http.INVALID_PARAMS)

    def test_initialized_is_accepted_without_a_body(self):
        raw = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
        self.assertEqual(self.post(raw, accept=ACCEPT), (202, None))

    def test_tools_list_after_initialize_is_the_same_registry(self):
        for version in ("2025-11-25", "2025-06-18"):
            with self.subTest(version):
                status, payload = self.legacy("tools/list", version=version)
                self.assertEqual(status, 200)
                self.assertEqual(payload["result"]["tools"], agent_tools.listing())
                self.assertNotIn("resultType", payload["result"])

    def test_tools_call_of_a_listed_tool_goes_through_dispatch(self):
        status, payload = self.legacy("tools/call", {"name": "open_outing", "arguments": sample_args()})
        self.assertEqual(status, 200)
        self.assertFalse(payload["result"]["isError"])
        self.assertEqual(payload["result"]["structuredContent"]["outingId"], "out_001")

    def test_a_human_verb_is_an_unknown_tool(self):
        for verb in VERBS:
            with self.subTest(verb):
                answer = self.legacy("tools/call", {"name": verb, "arguments": {}})
                self.assertRpcError(answer, 200, mcp_http.INVALID_PARAMS)
                self.assertEqual(answer[1]["error"]["data"], {"outcome": "not_a_tool"})

    def test_a_refusal_for_a_listed_tool_is_is_error(self):
        asked = {"name": "read_outing", "arguments": {"outing_id": "none"}}
        status, payload = self.legacy("tools/call", asked)
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["isError"])

    def test_ping_is_answered_in_this_era_only(self):
        self.assertEqual(self.legacy("ping")[1]["result"], {})
        self.assertRpcError(self.modern("ping"), 404, mcp_http.METHOD_NOT_FOUND)

    def test_an_unknown_method_is_method_not_found(self):
        self.assertRpcError(self.legacy("resources/list"), 200, mcp_http.METHOD_NOT_FOUND)

    def test_a_request_with_no_usable_version_is_refused_naming_the_three(self):
        for sent in (None, "2025-03-26", "1999-01-01"):
            with self.subTest(sent):
                status, payload = self.post(
                    b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}', **headers(version=sent)
                )
                self.assertEqual((status, payload["error"]["code"]), (400, mcp_http.UNSUPPORTED_VERSION))
                self.assertEqual(payload["error"]["data"]["supported"], list(mcp_http.SUPPORTED))
                for version in mcp_http.SUPPORTED:
                    self.assertIn(version, payload["error"]["message"])

    def test_the_two_eras_alternate_on_one_endpoint(self):
        self.assertEqual(self.modern("tools/list")[0], 200)
        self.assertEqual(self.initialize("2025-11-25")[0], 200)
        self.assertEqual(self.legacy("tools/list")[0], 200)
        self.assertEqual(self.modern("server/discover")[0], 200)

    def test_the_modern_header_without_metadata_is_malformed_and_not_legacy(self):
        answer = self.post(b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}', **headers("tools/list"))
        self.assertRpcError(answer, 400, mcp_http.INVALID_PARAMS)


class HttpEndpoint(unittest.TestCase):
    """The same endpoint at its address, over a socket."""

    def setUp(self):
        self.served = Served()
        self.served.__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)
        self.browser = Browser(self.served)
        self.browser.open()
        self.token = self.browser.state()["agentAddress"].rsplit("/", 1)[1]
        self.path = f"/agent/{self.token}/mcp"

    def post(self, message, path=None, **sent):
        raw = json.dumps(message).encode()
        return self.served.call("POST", path or self.path, raw=raw, headers={"Accept": ACCEPT, **sent})

    def test_a_modern_call_over_a_socket(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
        reply = self.post(message, **{"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(len(reply.json["result"]["tools"]), 8)
        self.assertNotIn("mcp-session-id", reply.headers)

    def test_get_and_delete_are_405_and_name_post(self):
        for method in ("GET", "DELETE", "PUT"):
            with self.subTest(method):
                reply = self.served.call(method, self.path, headers={"Accept": "text/event-stream"})
                self.assertEqual(reply.status, 405)
                self.assertEqual(reply.headers["allow"], "POST")

    def test_a_stray_session_header_is_ignored_and_none_is_issued(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
        reply = self.post(message, **{"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list",
                                      "Mcp-Session-Id": "stale", "Last-Event-ID": "9"})
        self.assertEqual(reply.status, 200)
        self.assertNotIn("mcp-session-id", reply.headers)

    def test_a_cookie_and_a_same_origin_label_never_upgrade_the_caller(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "open_outing", "arguments": sample_args(), "_meta": META}}
        reply = self.post(message, **{
            "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "open_outing",
            "Cookie": self.browser.cookie, "Sec-Fetch-Site": "same-origin", "Origin": self.served.origin,
        })
        opened = reply.json["result"]["structuredContent"]
        self.assertTrue(all("link" not in m for m in opened["members"]))
        message["params"] = {"name": "resolve_match", "arguments": {}, "_meta": META}
        message["id"] = 2
        verb = self.post(message, **{
            "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "resolve_match",
            "Cookie": self.browser.cookie, "Sec-Fetch-Site": "same-origin", "Origin": self.served.origin,
        })
        self.assertEqual((verb.status, verb.json["error"]["data"]["outcome"]), (400, "not_a_tool"))

    def test_an_unknown_token_is_404_and_a_foreign_origin_is_403(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
        sent = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}
        self.assertEqual(self.post(message, path="/agent/not-a-token/mcp", **sent).status, 404)
        self.assertEqual(self.post(message, Origin="https://elsewhere.example", **sent).status, 403)
        self.assertEqual(self.post(message, Origin=self.served.origin, **sent).status, 200)

    def test_the_content_type_and_the_size_are_checked_before_the_protocol(self):
        raw = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        plain = {"Accept": ACCEPT, "Content-Type": "text/plain"}
        reply = self.served.call("POST", self.path, raw=raw, headers=plain)
        self.assertEqual(reply.status, 415)
        big = self.served.call("POST", self.path, raw=b" " * (64 * 1024 + 1), headers={"Accept": ACCEPT})
        self.assertEqual(big.status, 413)

    def test_the_endpoint_shares_the_agent_addresss_rate_limit(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}
        sent = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}
        statuses = [self.post(message, **sent).status for _ in range(31)]
        self.assertEqual(statuses[:30], [200] * 30)
        self.assertEqual(statuses[30], 429)
        dispatch = self.served.call("POST", f"/agent/{self.token}/dispatch", {"tool": "spend_report"})
        self.assertEqual(dispatch.status, 429)

    def test_the_two_eras_share_the_port_over_a_socket(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"}}
        reply = self.post(init)
        self.assertEqual(reply.json["result"]["protocolVersion"], "2025-06-18")
        initialized = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
        done = self.served.call("POST", self.path, raw=initialized, headers={"Accept": ACCEPT})
        self.assertEqual((done.status, done.body), (202, b""))
        listed = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                           **{"MCP-Protocol-Version": "2025-06-18"})
        self.assertEqual(len(listed.json["result"]["tools"]), 8)


if __name__ == "__main__":
    unittest.main()
