import ast
import dataclasses
import json
import os
import secrets
import unittest

from common_ground import sources, wire
from common_ground.gateway import Actor, Gateway
from tests.session import Session, verified
from tests.support import Canned, Stub, fake_key
from tests.test_outings import sample_args

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "common_ground")
ROOT = os.path.join(PACKAGE, "..")


def found_in(needle, node, path="$", seen=None):
    """Every place inside `node` (containers, dataclasses, object attributes) where `needle` occurs."""
    seen = set() if seen is None else seen
    if id(node) in seen:
        return []
    seen.add(id(node))
    if isinstance(node, (str, bytes)):
        text = node if isinstance(node, str) else node.decode("latin-1")
        return [path] if needle in text else []
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            hits += found_in(needle, key, f"{path}.<key>", seen)
            hits += found_in(needle, value, f"{path}[{key!r}]", seen)
    elif isinstance(node, (list, tuple, set, frozenset)):
        for i, value in enumerate(node):
            hits += found_in(needle, value, f"{path}[{i}]", seen)
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            hits += found_in(needle, getattr(node, f.name), f"{path}.{f.name}", seen)
    elif hasattr(node, "__dict__") and not isinstance(node, type):
        for key, value in vars(node).items():
            hits += found_in(needle, value, f"{path}.{key}", seen)
    return hits


class Run:
    """A walk through the gateway on a live source over a real loopback socket, every answer kept."""

    def __init__(self):
        self.key = fake_key()
        self.marker = "Zq" + secrets.token_hex(6)
        self.fake = sources.FakeSource()
        for place in self.fake._places:
            place["name"] = f"{self.marker} {place['name']}"
            place["address"] = f"{self.marker} {place['address']}"
        self.answers = []

    def go(self, base_url, key=None):
        source = sources.LiveSource(key or self.key, daily_ceiling=1000, cache_ttl_s=60, base_url=base_url)
        self.session = Session(source, provider="live", api_key=key or self.key)
        s = self.session
        record = lambda answer: self.answers.append(answer) or answer  # noqa: E731
        s.run = lambda tool, args=None, actor=None: record(s.gateway.dispatch(tool, args, actor or s.agent))
        return s


def walk(s):
    oid = s.open(actor=s.organiser)
    s.search_all(oid, actor=s.organiser)
    s.resolve_all(oid)
    s.choose_kind(oid, actor=s.organiser)
    result = s.compare(oid, actor=s.organiser)
    place = result["common"][0]["placeId"]
    s.ok("show_evidence", {"outing_id": oid, "place_id": place})
    draft = s.ok("write_draft", {"outing_id": oid, "place_id": place, "kind": "invitation"})
    s.ok("pick_place", {"outing_id": oid, "place_id": place, "revision": s.outing(oid)["revision"]},
         s.organiser)
    s.ok("sign_off_message", {
        "outing_id": oid, "draft_id": draft["draftId"], "sender_name": "Noor",
        "revision": s.outing(oid)["revision"],
    }, s.organiser)
    s.ok("read_outing", {"outing_id": oid})
    s.ok("spend_report", {})
    return oid


class TheKeyReachesQlooInOneHeaderOnly(unittest.TestCase):
    def test_no_key_response_string_or_token_reaches_a_place_it_should_not(self):
        run = Run()
        with Stub(run.fake, run.key) as stub, verified():
            s = run.go(stub.url)
            oid = walk(s)
        document = s.gateway.document
        workspace = document["workspaces"][0]
        out = workspace["outings"][0]

        self.assertTrue(stub.requests)
        for seen in stub.requests:
            self.assertEqual(seen["headers"]["X-Api-Key"], run.key)
            self.assertNotIn(run.key, seen["path"])
            self.assertEqual([n for n, v in seen["headers"].items() if run.key in v and n != "X-Api-Key"], [])

        for what, thing in (
            ("the document", document),
            ("every answer", run.answers),
            ("the gateway's text", (repr(s.gateway), str(s.gateway), s.gateway.config)),
            ("the source's text", (repr(s.source), str(s.source), s.source.report())),
        ):
            with self.subTest(what):
                self.assertEqual(found_in(run.key, thing), [])
        self.assertEqual(found_in(run.key, s.source), ["$._key"])
        self.assertEqual(found_in(run.key, s.gateway), ["$.source._key"])

        quiet = {"calls": document["calls"], "activityLog": workspace["activityLog"],
                 "trace": out["trace"], "budget": out["budget"]}
        self.assertEqual(found_in(run.marker, quiet), [])
        self.assertEqual(found_in(run.marker, [a for a in run.answers if not a["ok"]]), [])
        self.assertTrue(found_in(run.marker, out["places"]))

        tokens = [m["token"] for m in out["members"]] + [workspace["agentToken"], workspace["id"]]
        opening = [a for a in run.answers if a["ok"] and {"outingId", "members"} <= set(a["result"])]
        elsewhere = [a for a in run.answers if a not in opening]
        for token in tokens:
            with self.subTest("a token stays out of the log, the ledger, the trace and every other answer"):
                self.assertEqual(found_in(token, quiet), [])
                self.assertEqual(found_in(token, elsewhere), [])
        self.assertIn(oid, [o["id"] for o in workspace["outings"]])

    def test_the_organiser_gets_the_links_once_and_the_agent_never(self):
        run = Run()
        with Stub(run.fake, run.key) as stub, verified():
            s = run.go(stub.url)
            agent = s.ok("open_outing", sample_args())
            organiser = s.ok("open_outing", sample_args(), s.organiser)
        tokens = [m["token"] for m in s.outing(organiser["outingId"])["members"]]
        agents = [m["token"] for m in s.outing(agent["outingId"])["members"]]
        self.assertEqual(found_in(agents[0], run.answers[0]), [])
        self.assertTrue(all(found_in(t, run.answers[1]) for t in tokens))


class Errors(unittest.TestCase):
    def failed(self, source, key):
        s = Session(source, provider="live", api_key=key)
        oid = s.open(actor=s.organiser)
        answer = s.gateway.dispatch(
            "look_up_favourite", {"outing_id": oid, "member_id": "m1", "favourite_id": "f1"}, s.organiser
        )
        return s, answer

    def check(self, s, answer, *needles):
        self.assertFalse(answer["ok"])
        for needle in needles:
            self.assertEqual(found_in(needle, answer), [])
            self.assertEqual(found_in(needle, s.gateway.document), [])
            self.assertEqual(found_in(needle, repr(answer)), [])

    def test_a_401_whose_body_echoes_the_key_and_a_place_name(self):
        run = Run()
        wrong = fake_key()
        with Stub(run.fake, run.key, echo_key_in_errors=True) as stub, verified():
            source = sources.LiveSource(wrong, daily_ceiling=10, cache_ttl_s=60, base_url=stub.url)
            s, answer = self.failed(source, wrong)
        self.assertEqual((answer["outcome"], answer["error"]["status"]), ("qloo_auth", 401))
        self.check(s, answer, wrong, run.key, "invalid key")

    def test_a_5xx_and_a_400_whose_bodies_carry_the_key_and_a_marker(self):
        for status in (400, 404, 429, 503):
            key, marker = fake_key(), "Zq" + secrets.token_hex(6)
            body = {"error": {"message": f"{marker} {key}"}}
            with self.subTest(status), Stub(Canned(status, body), key) as stub, verified():
                source = sources.LiveSource(key, daily_ceiling=10, cache_ttl_s=60, base_url=stub.url,
                                            sleep=lambda seconds: None)
                s, answer = self.failed(source, key)
            self.assertEqual(answer["error"]["status"], status)
            self.check(s, answer, key, marker)

    def test_a_lost_connection_names_neither_the_address_nor_the_key(self):
        key = fake_key()
        with verified():
            source = sources.LiveSource(key, daily_ceiling=10, cache_ttl_s=60, base_url="http://127.0.0.1:1")
            s, answer = self.failed(source, key)
        self.assertEqual((answer["outcome"], answer["error"]["status"]), ("qloo_unavailable", 0))
        self.check(s, answer, key, "127.0.0.1", "http://")

    def test_a_body_that_is_not_json_and_one_of_an_unknown_shape(self):
        for body in (b"<html>Zqmarker %s</html>", {"unexpected": "Zqmarker %s"}):
            key = fake_key()
            payload = body % key.encode() if isinstance(body, bytes) else {"unexpected": f"Zqmarker {key}"}
            with Stub(Canned(200, payload), key) as stub, verified():
                source = sources.LiveSource(key, daily_ceiling=10, cache_ttl_s=60, base_url=stub.url)
                s, answer = self.failed(source, key)
            self.assertEqual(answer["outcome"], "qloo_unexpected_shape")
            self.check(s, answer, key, "Zqmarker")

    def test_a_base_url_that_is_not_qloos_is_refused_before_the_key_is_sent(self):
        key = fake_key()
        with verified():
            source = sources.LiveSource(key, daily_ceiling=10, cache_ttl_s=60, base_url="https://example.com")
            s, answer = self.failed(source, key)
        self.assertEqual(answer["outcome"], "bad_base_url")
        self.check(s, answer, key, "example.com")


class NothingWritesAnywhere(unittest.TestCase):
    def tree(self):
        found = set()
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            found |= {os.path.join(folder, f) for f in files}
        return found

    def test_a_whole_run_leaves_the_repository_exactly_as_it_was(self):
        before = self.tree()
        run = Run()
        with Stub(run.fake, run.key) as stub, verified():
            walk(run.go(stub.url))
        self.assertEqual(self.tree(), before)

    def test_no_module_opens_a_file_for_writing_logs_or_reads_the_environment_but_settings(self):
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                with self.subTest(module=name, line=getattr(node, "lineno", 0)):
                    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "open":
                        modes = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                        modes += [k.value.value for k in node.keywords if k.arg == "mode"]
                        self.assertFalse([m for m in modes if set(m) & set("wax+")])
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                        self.assertNotIn("logging", names)
                    if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                        self.assertEqual(name, "settings.py")
                    if isinstance(node, ast.Attribute) and node.attr in ("write_text", "write_bytes", "mkdir",
                                                                          "makedirs"):
                        self.fail("a module writes to the file system")

    def test_the_only_modules_that_open_a_connection_are_wire_the_server_and_the_stdio_relay(self):
        forbidden = ("urllib.request", "urllib.error", "socket", "http.client", "http.server", "ssl")
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py") or name in ("wire.py", "web.py", "mcp_stdio.py"):
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
                    imported |= {f"{node.module}.{a.name}" for a in node.names}
            with self.subTest(name):
                self.assertFalse([i for i in imported if i.startswith(forbidden)])

    def test_the_stdio_relay_reaches_the_agent_address_and_nothing_that_holds_the_key(self):
        with open(os.path.join(PACKAGE, "mcp_stdio.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        holders = {"settings", "wire", "sources", "gateway", "records", "qloo_calls"}
        self.assertEqual(imported & holders, set())


class TheGatewayDoesNotHoldTheKey(unittest.TestCase):
    def test_it_keeps_only_whether_a_key_is_set(self):
        key = fake_key()
        s = Session(sources.FakeSource(), provider="fake", api_key=key)
        self.assertIsNone(s.gateway.config.api_key)
        self.assertEqual(s.gateway.key_status, "set")
        self.assertEqual(s.ok("spend_report", {})["key"], "set")
        self.assertEqual(found_in(key, s.gateway), [])

    def test_the_settings_object_hides_it_from_its_own_text(self):
        key = fake_key()
        self.assertNotIn(key, repr(Session(provider="fake", api_key=key).config))


if __name__ == "__main__":
    unittest.main()
