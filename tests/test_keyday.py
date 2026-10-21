import contextlib
import hashlib
import io
import re
import tempfile
import unittest
from urllib.parse import parse_qsl, urlsplit

from common_ground import __main__ as cli
from common_ground import keyday, measured, sources, wire
from tests.support import Stub, fake_key, strings_in

NAMES = ("Sample Eatery", "Sample Band", "Sample Film")
IMPLIED = {
    "sample eatery": "urn:entity:place",
    "sample band": "urn:entity:artist",
    "sample film": "urn:entity:movie",
}
OUR_TEXT = {"__builtins__": {}, "frozenset": frozenset}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class Honest(sources.FakeSource):
    """Answers the three probe names with the type their domain implies."""

    def candidate_type_order(self, text, types):
        first = IMPLIED.get(text.lower(), types[0])
        return [first] + [t for t in types if t != first]


class Thin(Honest):
    """Only 28 places per group search, and a ranking of more than 25 ids is refused."""

    def respond(self, path, params):
        values = dict(params)
        if len([i for i in values.get("filter.results.entities", "").split(",") if i]) > 25:
            return 400, {"error": {"message": "too many ids"}}
        status, body = super().respond(path, params)
        if status == 200 and path == "/v2/insights" and "filter.results.entities" not in values:
            body["results"]["entities"] = body["results"]["entities"][:28]
        return status, body


class IgnoresLocationQuery(Thin):
    def keeps(self, place, values):
        return super().keeps(place, {k: v for k, v in values.items() if k != "filter.location.query"})


class IgnoresTheSignal(Honest):
    def _score(self, entity_id, index):
        return 0.4 + 0.5 * int(hashlib.sha256(str(index).encode()).hexdigest()[:6], 16) / 0xFFFFFF


class WrongTypes(Honest):
    def candidate_type_order(self, text, types):
        return ["urn:entity:book"] + [t for t in types if t != "urn:entity:book"]


class RenamedIds(Honest):
    def respond(self, path, params):
        status, body = super().respond(path, params)
        if path == "/v2/insights" and status == 200:
            for entity in body["results"]["entities"]:
                entity["id"] = entity.pop("entity_id")
        return status, body


def probe(source, key=None, probe_key=None):
    key = key or fake_key()
    with Stub(source, key) as stub:
        report = keyday.run(NAMES, probe_key or key, base_url=stub.url)
    return report, stub, key


def forbidden(stub):
    """Every string a stub answered with that is data and not this app's own vocabulary."""
    seen = {s for body in stub.responses for s in strings_in(body) if len(s) >= 6}
    seen = {s for s in seen if not s.startswith("urn:entity:")}
    return seen | set(NAMES)


class WholeRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.stub, cls.key = probe(Honest())
        cls.text = cls.report.render()

    def test_eleven_calls_and_every_threshold_passes(self):
        self.assertEqual(self.report.calls, 11)
        self.assertEqual(len(self.stub.requests), 11)
        self.assertEqual(self.report.passed, {"T1": True, "T2": True, "T3": True, "T4": True, "T5": True})

    def test_no_request_repeats(self):
        paths = [r["path"] for r in self.stub.requests]
        self.assertEqual(len(paths), len(set(paths)))

    def test_every_request_is_a_get_with_the_key_in_the_header_only(self):
        for request in self.stub.requests:
            self.assertEqual(request["command"], "GET")
            self.assertEqual(request["headers"]["X-Api-Key"], self.key)
            self.assertNotIn(self.key, request["path"])

    def test_nothing_in_the_output_is_a_key_a_name_an_id_or_a_stub_string(self):
        self.assertNotIn(self.key, self.text)
        self.assertFalse(UUID.findall(self.text))
        for secret in forbidden(self.stub):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, self.text)
        for name in NAMES:
            self.assertNotIn(name, self.text)

    def test_the_output_shows_shapes_counts_and_the_thresholds(self):
        self.assertIn("$.results.entities[].query.affinity: number x50", self.text)
        self.assertIn("P3 group search, city 1: status 200, 50 places", self.text)
        self.assertIn("the two upper halves differ in", self.text)
        for threshold in ("T1 PASS", "T2 PASS", "T3 PASS", "T4 PASS", "T5 PASS"):
            self.assertIn(threshold, self.text)
        self.assertIn("calls made: 11 of 14", self.text)

    def test_the_block_replaces_the_defaults_and_empties_the_set(self):
        namespace = {}
        exec(self.report.block, dict(OUR_TEXT), namespace)
        self.assertEqual(namespace["UNVERIFIED"], frozenset())
        self.assertEqual(namespace["LONG_LIST"], 50)
        self.assertEqual(namespace["SAMPLE_CITY"], measured.SAMPLE_CITY)
        self.assertEqual(namespace["CONDITIONS_OK"], measured.CONDITIONS_OK)
        self.assertEqual(namespace["AFFINITY_PATH"], ("query", "affinity"))
        self.assertEqual(
            namespace["RESPONSE_SHAPES"], frozenset({"search", "tags", "group_search", "ranking"})
        )
        self.assertEqual(len(namespace["AFFINITY_SCALE"]), 2)
        self.assertTrue(all(0 <= low <= high <= 1 for low, high in namespace["AFFINITY_SCALE"]))
        self.assertFalse(UUID.findall(self.report.block))

    def test_p5_asks_exactly_what_the_comparison_will_ask(self):
        group = next(r for r in self.stub.requests if "signal.interests.entities=" in r["path"]
                     and "filter.results.entities" not in r["path"] and "filter.hours" in r["path"]
                     and "filter.exclude.entities" in r["path"] and "filter.tags" in r["path"])
        group_params = dict(parse_qsl(urlsplit(group["path"]).query))
        position = [r["path"] for r in self.stub.requests].index(group["path"])
        returned = [e["entity_id"] for e in self.stub.responses[position]["results"]["entities"]]
        rankings = [dict(parse_qsl(urlsplit(r["path"]).query)) for r in self.stub.requests
                    if "filter.results.entities" in r["path"]]
        self.assertEqual(len(rankings), 2)
        for params in rankings:
            self.assertEqual(params["filter.results.entities"].split(","), returned)
            self.assertEqual(params["take"], str(len(returned)))
            self.assertEqual(len(params["signal.interests.entities"].split(",")), 1)
            self.assertNotIn("filter.exclude.entities", params)
            for name in ("filter.location.query", "filter.hours", "filter.price_level.min",
                         "filter.price_level.max", "filter.tags"):
                self.assertEqual(params[name], group_params[name])
        signals = [r["signal.interests.entities"] for r in rankings]
        self.assertNotEqual(signals[0], signals[1])

    def test_the_first_three_calls_are_the_three_names_in_order(self):
        names = [dict(parse_qsl(urlsplit(r["path"]).query))["query"] for r in self.stub.requests[:3]]
        self.assertEqual(names, list(NAMES))
        self.assertIn("types=", self.stub.requests[0]["path"])


class Limits(unittest.TestCase):
    def test_the_worst_case_is_fourteen_calls_and_not_one_more(self):
        report, stub, _ = probe(Thin())
        self.assertEqual(report.calls, 14)
        self.assertEqual(len(stub.requests), 14)
        self.assertIn("not accepted at 28 ids: the same two calls at 25", report.render())
        self.assertIn("P3 group search, city 2", report.render())
        self.assertEqual(report.block.count("LONG_LIST = 25"), 1)
        self.assertEqual(report.passed["T3"], True)

    def test_a_fifteenth_call_is_never_made(self):
        report, stub, _ = probe(IgnoresLocationQuery())
        self.assertEqual(len(stub.requests), 14)
        self.assertEqual(report.calls, 14)
        text = report.render()
        self.assertIn("location by the geocode name instead: status 200, works", text)
        self.assertIn("stopped: the 14-call budget is spent", text)
        self.assertIn("filter.geocode.name", report.block)

    def test_a_failing_server_is_asked_once_and_the_probe_moves_on(self):
        key = fake_key()
        from tests.support import Canned
        with Stub(Canned(503, {"error": {"message": "busy"}}), key) as stub:
            report = keyday.run(NAMES, key, base_url=stub.url)
        self.assertEqual(report.calls, 4)
        paths = [r["path"] for r in stub.requests]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(report.passed, {"T1": False, "T2": False, "T3": False, "T4": False, "T5": False})
        self.assertIsNone(report.block)

    def test_a_wrong_key_stops_after_the_names_and_one_deliberately_wrong_call(self):
        real, wrong = fake_key(), fake_key()
        report, stub, _ = probe(Honest(), key=real, probe_key=wrong)
        self.assertEqual(report.calls, 4)
        self.assertNotIn(wrong, report.render())
        self.assertNotIn(real, report.render())
        self.assertIn("P6 a deliberately wrong key: status 401, named qloo_auth", report.render())
        self.assertIsNone(report.block)


class Verdicts(unittest.TestCase):
    def test_a_stub_that_ignores_the_signal_fails_t3_and_gets_no_block(self):
        report, _, _ = probe(IgnoresTheSignal())
        self.assertFalse(report.passed["T3"])
        self.assertTrue(report.passed["T1"])
        self.assertIsNone(report.block)
        self.assertIn("the two upper halves differ in 0 places", report.render())
        self.assertIn("no constants block", report.render())

    def test_wrong_types_leave_the_favourite_types_unverified_and_nothing_else(self):
        report, _, _ = probe(WrongTypes())
        namespace = {}
        exec(report.block, dict(OUR_TEXT), namespace)
        self.assertEqual(namespace["UNVERIFIED"], frozenset({"FAVOURITE_TYPES"}))

    def test_a_shape_the_readers_do_not_know_is_reported_not_guessed(self):
        report, _, _ = probe(RenamedIds())
        text = report.render()
        self.assertFalse(report.passed["T1"])
        self.assertIn("refused qloo_unexpected_shape at $.results.entities[0].entity_id", text)
        self.assertEqual(report.calls, 7)

    def test_no_explainability_fails_t4_only(self):
        report, _, _ = probe(Honest(with_explainability=False))
        self.assertEqual(report.passed, {"T1": True, "T2": True, "T3": True, "T4": False, "T5": True})
        self.assertIn("EXPLAIN_PATH = None", report.block)
        self.assertIn("LEAN_PATH = None", report.block)

    def test_no_affinity_fails_t5_only(self):
        report, _, _ = probe(Honest(with_affinity=False))
        self.assertEqual(report.passed, {"T1": True, "T2": True, "T3": True, "T4": True, "T5": False})
        self.assertIn("AFFINITY_PATH = None", report.block)
        self.assertIn("AFFINITY_SCALE = None", report.block)


class Command(unittest.TestCase):
    def run_cli(self, argv, environ):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stderr(err):
            code = cli.main(argv, environ=environ, out=out, cwd=empty)
        return code, out.getvalue(), err.getvalue()

    def test_a_run_prints_the_report_and_exits_zero_when_t1_to_t3_pass(self):
        key = fake_key()
        with Stub(Honest(), key) as stub:
            argv = ["probe", "--base-url", stub.url] + [a for n in NAMES for a in ("--favourite", n)]
            code, out, err = self.run_cli(argv, {"QLOO_API_KEY": key})
        self.assertEqual((code, err), (0, ""))
        self.assertIn("T3 PASS", out)
        self.assertNotIn(key, out)

    def test_no_key_names_the_setting_and_exits_two(self):
        argv = ["probe"] + [a for n in NAMES for a in ("--favourite", n)]
        code, out, err = self.run_cli(argv, {})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("QLOO_API_KEY", err)

    def test_three_favourites_are_needed(self):
        argv = ["probe", "--favourite", "a", "--favourite", "b"]
        code, out, err = self.run_cli(argv, {"QLOO_API_KEY": fake_key()})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("three times", err)

    def test_a_base_url_beyond_loopback_is_refused_before_a_key_is_sent(self):
        key = fake_key()
        argv = ["probe", "--base-url", "https://example.com"] + [a for n in NAMES for a in ("--favourite", n)]
        code, out, err = self.run_cli(argv, {"QLOO_API_KEY": key})
        self.assertNotIn(key, out + err)
        self.assertEqual(code, 1)
        self.assertIn("T1 FAIL", out)

    def test_a_failure_exits_one(self):
        key = fake_key()
        with Stub(IgnoresTheSignal(), key) as stub:
            argv = ["probe", "--base-url", stub.url] + [a for n in NAMES for a in ("--favourite", n)]
            code, out, _ = self.run_cli(argv, {"QLOO_API_KEY": key})
        self.assertEqual(code, 1)
        self.assertIn("T3 FAIL", out)


class TheWrapperHasNoNetworkOfItsOwn(unittest.TestCase):
    def test_keyday_sends_only_through_wire(self):
        with open(keyday.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotRegex(source, r"urllib|socket|http\.client|requests")
        self.assertIs(keyday.run.__kwdefaults__["send"], wire.send)


if __name__ == "__main__":
    unittest.main()
