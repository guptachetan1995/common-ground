"""The stdio relay, case by case: both protocol eras, the registry as the only tool list, a human-only verb
refused, malformed and over-long input, an unreachable or hostile server, and the agent's token kept out of
every line it writes. The hosted side is a real server on a loopback port or a scripted stand-in."""
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common_ground import agent_tools, mcp_http, mcp_stdio, outings, person_verbs
from tests.served import Browser, Served
from tests.test_outings import sample_args

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VERBS = sorted(person_verbs.VERBS)
META = {
    mcp_http.META_VERSION: mcp_http.MODERN,
    mcp_http.META_CAPABILITIES: {},
    "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
}


def modern(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": {**(params or {}), "_meta": META}}


def legacy(method, params=None, id=1):
    message = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def initialize(version="2025-11-25", id=1):
    return legacy("initialize", {"protocolVersion": version, "capabilities": {},
                                 "clientInfo": {"name": "test", "version": "1"}}, id)


def encode(message):
    return message if isinstance(message, bytes) else json.dumps(message).encode()


def talk(address, *messages, send=mcp_stdio.post):
    data = b"".join(encode(m) + b"\n" for m in messages)
    out, err = io.BytesIO(), io.StringIO()
    code = mcp_stdio.run(address, io.BytesIO(data), out, err, send)
    lines = out.getvalue().split(b"\n")
    assert lines.pop() == b"", "every answer ends in a newline"
    return code, [json.loads(line) for line in lines], err.getvalue(), out.getvalue().decode()


class Standin:
    """A loopback server that answers every POST the same scripted way and keeps what it was sent."""

    def __init__(self, status=200, body=b"", headers=()):
        self.status, self.body, self.headers, self.seen = status, body, list(headers), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                sent = {name.lower(): value for name, value in self.headers.items()}
                outer.seen.append((self.path, sent, self.rfile.read(length)))
                self.send_response(outer.status)
                for name, value in outer.headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.token = secrets.token_hex(16)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}/agent/{self.token}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class Hosted(unittest.TestCase):
    def setUp(self):
        self.served = Served()
        self.served.__enter__()
        self.addCleanup(self.served.__exit__, None, None, None)
        self.browser = Browser(self.served)
        self.browser.open()
        self.address = self.browser.state()["agentAddress"]
        self.token = self.address.rsplit("/", 1)[1]

    def gateway_outing(self, outing_id="out_001"):
        document = self.served.session.gateway.document
        return outings.outing(document, self.browser.workspace["id"], outing_id)

    def assertNoToken(self, *texts):
        for text in texts:
            self.assertNotIn(self.token, text)


class ModernEra(Hosted):
    def test_discover_and_the_tool_list_are_the_hosted_endpoints_own(self):
        asked = (modern("server/discover", id=7), modern("tools/list", id="b"))
        code, replies, err, out = talk(self.address, *asked)
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in replies], [7, "b"])
        self.assertEqual(replies[0]["result"]["supportedVersions"], list(mcp_http.SUPPORTED))
        self.assertEqual(replies[1]["result"]["tools"], agent_tools.listing())
        names = [t["name"] for t in replies[1]["result"]["tools"]]
        self.assertEqual(len(names), 8)
        self.assertFalse(set(names) & set(VERBS))
        self.assertNoToken(err, out)

    def test_a_listed_tool_runs_as_the_agent(self):
        call = modern("tools/call", {"name": "open_outing", "arguments": sample_args()})
        _, replies, _, _ = talk(self.address, call)
        result = replies[0]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["outingId"], "out_001")
        self.assertEqual(self.browser.workspace["activityLog"][-1]["actor"], "agent")
        self.assertEqual(self.gateway_outing()["label"], sample_args()["label"])

    def test_each_human_verb_is_an_unknown_tool_and_changes_nothing(self):
        talk(self.address, modern("tools/call", {"name": "open_outing", "arguments": sample_args()}))
        before = json.dumps(self.gateway_outing(), sort_keys=True)
        calls = [modern("tools/call", {"name": verb, "arguments": {"outing_id": "out_001", "limit": 40,
                                                                    "place_id": "p", "revision": 1}}, id=i)
                 for i, verb in enumerate(VERBS)]
        _, replies, err, out = talk(self.address, *calls)
        self.assertEqual(len(replies), len(VERBS))
        for verb, reply in zip(VERBS, replies):
            with self.subTest(verb):
                self.assertEqual(reply["error"]["code"], mcp_http.INVALID_PARAMS)
                self.assertEqual(reply["error"]["data"], {"outcome": "not_a_tool"})
                self.assertNotIn("result", reply)
        self.assertEqual(json.dumps(self.gateway_outing(), sort_keys=True), before)
        self.assertIsNone(self.gateway_outing()["chosen"])
        self.assertNoToken(err, out)

    def test_a_refusal_for_a_listed_tool_is_a_result_with_is_error(self):
        asked = {"name": "show_evidence", "arguments": {"outing_id": "out_404", "place_id": "x"}}
        call = modern("tools/call", asked)
        _, replies, _, _ = talk(self.address, call)
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertIn("outcome", json.loads(replies[0]["result"]["content"][0]["text"]))

    def test_an_unsupported_version_is_the_hosted_endpoints_refusal_word_for_word(self):
        message = modern("tools/list")
        message["params"]["_meta"] = {**META, mcp_http.META_VERSION: "1999-01-01"}
        _, replies, _, _ = talk(self.address, message)
        self.assertEqual(replies[0]["error"]["code"], mcp_http.UNSUPPORTED_VERSION)
        self.assertEqual(replies[0]["error"]["data"]["supported"], list(mcp_http.SUPPORTED))


class LegacyEra(Hosted):
    def test_the_handshake_is_relayed_and_later_requests_carry_the_agreed_version(self):
        notice = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        asked = (initialize("2025-06-18"), notice, legacy("tools/list", id=2), legacy("ping", id=3))
        code, replies, err, out = talk(self.address, *asked)
        self.assertEqual(code, 0)
        self.assertEqual(len(replies), 3, "the notification gets no answer")
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[0]["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(replies[1]["result"]["tools"], agent_tools.listing())
        self.assertEqual(replies[2], {"jsonrpc": "2.0", "id": 3, "result": {}})
        self.assertNoToken(err, out)

    def test_a_version_the_server_does_not_serve_is_answered_with_the_one_it_does_and_used_after(self):
        _, replies, _, _ = talk(self.address, initialize("2024-11-05"), legacy("tools/list", id=2))
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(len(replies[1]["result"]["tools"]), 8)

    def test_without_a_handshake_the_request_is_refused_as_the_endpoint_refuses_it(self):
        _, replies, _, _ = talk(self.address, legacy("tools/list"))
        self.assertEqual(replies[0]["error"]["code"], mcp_http.UNSUPPORTED_VERSION)
        self.assertEqual(replies[0]["error"]["data"]["supported"], list(mcp_http.SUPPORTED))

    def test_a_listed_tool_runs_and_a_human_verb_is_not_a_tool(self):
        _, replies, _, _ = talk(
            self.address, initialize(),
            legacy("tools/call", {"name": "open_outing", "arguments": sample_args()}, id=2),
            *[legacy("tools/call", {"name": v, "arguments": {}}, id=10 + i) for i, v in enumerate(VERBS)],
        )
        self.assertFalse(replies[1]["result"]["isError"])
        self.assertEqual(self.gateway_outing()["label"], sample_args()["label"])
        for verb, reply in zip(VERBS, replies[2:]):
            with self.subTest(verb):
                self.assertEqual(reply["error"]["data"], {"outcome": "not_a_tool"})
                self.assertIn(verb, reply["error"]["message"])


class BadInput(Hosted):
    def test_a_line_that_is_not_json_gets_a_parse_error_and_the_next_line_is_still_served(self):
        _, replies, _, _ = talk(self.address, b"{not json", b"\xff\xfe", modern("tools/list", id=5))
        self.assertEqual([r.get("error", {}).get("code") for r in replies[:2]], [mcp_http.PARSE_ERROR] * 2)
        self.assertEqual([r["id"] for r in replies[:2]], [None, None])
        self.assertEqual(replies[2]["id"], 5)
        self.assertIn("result", replies[2])

    def test_a_batch_a_scalar_and_an_object_with_no_method_are_invalid_requests(self):
        _, replies, _, _ = talk(self.address, [modern("tools/list")], b'"hello"', b"42",
                                {"jsonrpc": "2.0", "id": 9}, {"jsonrpc": "2.0", "id": True, "method": "ping"})
        self.assertEqual([r["error"]["code"] for r in replies], [mcp_http.INVALID_REQUEST] * 5)
        self.assertEqual([r["id"] for r in replies], [None, None, None, 9, None])

    def test_blank_lines_and_a_clients_stray_response_get_no_answer(self):
        _, replies, err, _ = talk(self.address, b"", b"   ", {"jsonrpc": "2.0", "id": 4, "result": {}},
                                  modern("tools/list", id=6))
        self.assertEqual([r["id"] for r in replies], [6])
        self.assertIn("ignored", err)

    def test_a_line_over_the_limit_is_refused_unread_and_the_stream_goes_on(self):
        seen = []

        def counting(url, headers, body):
            seen.append(body)
            return mcp_stdio.post(url, headers, body)

        big = b"x" * (mcp_stdio.MAX_LINE + 10)
        _, replies, _, _ = talk(self.address, big, modern("tools/list", id=2), send=counting)
        self.assertEqual(replies[0]["error"]["code"], mcp_http.INVALID_REQUEST)
        self.assertIsNone(replies[0]["id"])
        self.assertIn(str(mcp_stdio.MAX_LINE), replies[0]["error"]["message"])
        self.assertEqual(replies[1]["id"], 2)
        self.assertEqual(len(seen), 1, "only the second line was sent on")

    def test_a_line_of_exactly_the_limit_is_sent_on(self):
        message = modern("tools/call", {"name": "read_outing", "arguments": {"pad": ""}}, id=3)
        message["params"]["arguments"]["pad"] = "p" * (mcp_stdio.MAX_LINE - len(json.dumps(message)))
        raw = json.dumps(message).encode()
        self.assertEqual(len(raw), mcp_stdio.MAX_LINE)
        _, replies, _, _ = talk(self.address, raw)
        self.assertEqual(replies[0]["id"], 3)
        self.assertNotEqual(replies[0].get("error", {}).get("code"), mcp_http.INVALID_REQUEST)

    def test_end_of_input_ends_it_with_status_zero_and_no_output(self):
        code, replies, err, out = talk(self.address)
        self.assertEqual((code, replies, out), (0, [], ""))
        self.assertNotIn("Traceback", err)


class WhatItSends(unittest.TestCase):
    ANSWER = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode()

    def sent(self, *messages):
        with Standin(body=self.ANSWER) as standin:
            talk(standin.address, *messages)
            return standin.seen, standin.token

    def test_a_modern_request_gets_the_headers_the_endpoint_reads_and_nothing_that_could_upgrade_it(self):
        seen, token = self.sent(modern("tools/call", {"name": "open_outing", "arguments": {}}))
        path, headers, body = seen[0]
        self.assertEqual(path, f"/agent/{token}/mcp")
        self.assertEqual(headers["mcp-protocol-version"], mcp_http.MODERN)
        self.assertEqual(headers["mcp-method"], "tools/call")
        self.assertEqual(headers["mcp-name"], "open_outing")
        self.assertEqual(headers["accept"], "application/json, text/event-stream")
        self.assertEqual(headers["content-type"], "application/json")
        for forbidden in ("cookie", "origin", "sec-fetch-site", "x-common-ground-as", "authorization"):
            self.assertNotIn(forbidden, headers)
        self.assertEqual(json.loads(body)["method"], "tools/call")

    def test_a_tool_name_that_is_not_plain_ascii_travels_in_the_base64_form_the_endpoint_decodes(self):
        seen, _ = self.sent(modern("tools/call", {"name": "café", "arguments": {}}))
        self.assertEqual(seen[0][1]["mcp-name"], "=?base64?Y2Fmw6k=?=")

    def test_the_handshake_has_no_version_header_and_what_follows_has_the_agreed_one(self):
        answer = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}).encode()
        with Standin(body=answer) as standin:
            talk(standin.address, initialize("2025-06-18"), legacy("tools/list", id=2))
        first, second = (headers for _, headers, _ in standin.seen)
        self.assertNotIn("mcp-protocol-version", first)
        self.assertEqual(second["mcp-protocol-version"], "2025-06-18")
        self.assertNotIn("mcp-method", second)

    def test_a_notification_is_delivered_and_gets_no_answer_whatever_the_server_says(self):
        refusal = b'{"jsonrpc":"2.0","id":null,"error":{"code":-32601,"message":"no"}}'
        with Standin(status=404, body=refusal) as s:
            _, replies, _, out = talk(s.address, {"jsonrpc": "2.0", "method": "notifications/cancelled"})
        self.assertEqual((replies, out), ([], ""))
        self.assertEqual(len(s.seen), 1)


class WhatTheServerMayAnswer(unittest.TestCase):
    def reply(self, status=200, body=b"", headers=(), message=None):
        with Standin(status=status, body=body, headers=headers) as standin:
            _, replies, err, out = talk(standin.address, message or modern("tools/list", id=11))
        for text in (err, out):
            self.assertNotIn(standin.token, text)
        return replies[0], standin

    def test_a_json_rpc_message_is_passed_on_on_one_line_even_when_the_server_prints_it_spread_out(self):
        spread = json.dumps({"jsonrpc": "2.0", "id": 11, "result": {"a": ["é"]}}, indent=4).encode()
        with Standin(body=spread) as standin:
            _, _, _, out = talk(standin.address, modern("tools/list", id=11))
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(json.loads(out)["result"], {"a": ["é"]})

    def test_a_json_rpc_error_with_an_http_error_status_is_passed_on_as_it_is(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 11, "error": {"code": -32022, "message": "m"}}).encode()
        reply, _ = self.reply(400, body)
        self.assertEqual(reply["error"], {"code": -32022, "message": "m"})

    def test_an_unknown_address_a_rate_limit_and_other_statuses_each_get_a_fixed_sentence(self):
        reply, _ = self.reply(404, b'{"ok":false,"outcome":"not_found"}')
        self.assertEqual((reply["id"], reply["error"]["code"]), (11, mcp_stdio.SERVER_ERROR))
        self.assertEqual(reply["error"]["message"], mcp_stdio.UNKNOWN_ADDRESS)
        reply, _ = self.reply(429, b'{"ok":false}', [("Retry-After", "7")])
        self.assertTrue(reply["error"]["message"].endswith("retry in 7 s"))
        reply, _ = self.reply(429, b'{"ok":false}', [("Retry-After", "soon")])
        self.assertEqual(reply["error"]["message"], mcp_stdio.LIMITED)
        for status in (403, 502, 503):
            reply, _ = self.reply(status, b"<html>bad gateway</html>")
            self.assertEqual(reply["error"]["message"], mcp_stdio.OTHER_STATUS.format(status))

    def test_a_200_that_is_not_a_json_rpc_message_is_replaced_by_a_sentence(self):
        for body in (b"ok\n", b"[]", b'{"result": 1}', b'"text"'):
            reply, _ = self.reply(200, body)
            self.assertEqual(reply["error"]["message"], mcp_stdio.OTHER_STATUS.format(200), body)

    def test_text_a_hostile_server_sends_back_is_never_relayed_nor_is_the_path_it_was_sent(self):
        with Standin(status=500, body=b"internal error at /agent/SECRETPATH with key=abcd1234") as standin:
            _, replies, err, out = talk(standin.address, modern("tools/list", id=1))
        for text in (err, out, json.dumps(replies)):
            self.assertNotIn("SECRETPATH", text)
            self.assertNotIn("abcd1234", text)
            self.assertNotIn(standin.token, text)

    def test_a_redirect_is_not_followed_so_the_token_goes_nowhere_else(self):
        with Standin(body=b"") as elsewhere:
            with Standin(status=302, headers=[("Location", elsewhere.address + "/mcp")]) as first:
                _, replies, err, out = talk(first.address, modern("tools/list", id=1))
            self.assertEqual(elsewhere.seen, [])
        self.assertEqual(replies[0]["error"]["message"], mcp_stdio.OTHER_STATUS.format(302))
        self.assertNotIn(first.token, err + out)


class Unreachable(unittest.TestCase):
    def closed_address(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_hex(16)
        return f"http://127.0.0.1:{port}/agent/{token}", token

    def test_each_request_is_answered_with_a_sentence_and_the_relay_carries_on(self):
        address, token = self.closed_address()
        code, replies, err, out = talk(address, modern("tools/list", id=1), legacy("ping", id=2))
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in replies], [1, 2])
        for reply in replies:
            self.assertEqual(reply["error"]["code"], mcp_stdio.SERVER_ERROR)
            self.assertEqual(reply["error"]["message"], mcp_stdio.UNREACHABLE)
        self.assertNotIn(token, err + out)

    def test_an_undeliverable_notification_is_a_line_on_stderr_and_nothing_on_stdout(self):
        address, token = self.closed_address()
        _, replies, err, out = talk(address, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((replies, out), ([], ""))
        self.assertIn("could not be delivered", err)
        self.assertNotIn(token, err)


class TheAddress(unittest.TestCase):
    def test_the_forms_the_page_and_the_readme_give_are_accepted(self):
        token = "a" * 32
        for given in (f"https://demo.example/agent/{token}", f"https://demo.example/agent/{token}/",
                      f"https://demo.example/agent/{token}/mcp", f"http://127.0.0.1:8761/agent/{token}",
                      f"http://localhost:8761/agent/{token}/mcp", f"http://[::1]:8761/agent/{token}"):
            with self.subTest(given):
                self.assertTrue(mcp_stdio.endpoint(given).endswith(f"/agent/{token}/mcp"))

    def test_anything_else_is_refused_without_the_text_being_echoed(self):
        token = secrets.token_hex(16)
        for given in (f"http://demo.example/agent/{token}", f"https://demo.example/agent/{token}/extra",
                      f"https://demo.example/agent/{token}?x=1", f"https://user@demo.example/agent/{token}",
                      f"ftp://demo.example/agent/{token}", f"https://demo.example/other/{token}",
                      "https://demo.example/agent/", "https://demo.example", "", "not a url",
                      f"https://demo.example:notaport/agent/{token}"):
            with self.subTest(given):
                with self.assertRaises(mcp_stdio.AddressError) as caught:
                    mcp_stdio.endpoint(given)
                self.assertNotIn(token, str(caught.exception))
                code, replies, err, out = talk(given)
                self.assertEqual((code, replies, out), (2, [], ""))
                self.assertNotIn(token, err)


class CommandLine(Hosted):
    def run_command(self, address, data, **extra):
        with tempfile.TemporaryDirectory() as cwd:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.path.abspath(ROOT), **extra}
            return subprocess.run(
                [sys.executable, "-m", "common_ground", "mcp", "--address", address],
                input=data, capture_output=True, cwd=cwd, env=env, timeout=60,
            )

    def test_it_relays_over_real_pipes_ends_at_eof_with_zero_and_needs_no_settings(self):
        data = b"".join(encode(m) + b"\n" for m in (modern("tools/list", id=1), initialize(id=2)))
        done = self.run_command(self.address, data, COMMON_GROUND_PORT="not a number", QLOO_API_KEY="")
        self.assertEqual(done.returncode, 0, done.stderr)
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertEqual(replies[0]["result"]["tools"], agent_tools.listing())
        self.assertIn(b"relaying to 127.0.0.1:", done.stderr)
        self.assertNoToken(done.stdout.decode(), done.stderr.decode())

    def test_a_bad_address_exits_two_with_nothing_on_stdout(self):
        done = self.run_command(f"http://example.invalid/agent/{self.token}", b"")
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertNoToken(done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
