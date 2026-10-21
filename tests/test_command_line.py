import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from common_ground import __main__ as cli
from common_ground import sources, wire
from tests.session import verified
from tests.support import Stub, fake_key

SCENARIO = os.path.join(os.path.dirname(__file__), "..", "scenarios", "friday-table.json")


def run(*argv, environ=None):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stderr(err):
        code = cli.main(list(argv), environ=environ or {}, out=out, cwd=empty)
    return code, out.getvalue(), err.getvalue()


class PlanOnTheFakeSource(unittest.TestCase):
    def test_it_prints_scenario_as_trace_and_is_fourteen_of_thirty(self):
        code, out, err = run("plan", SCENARIO, "--provider", "fake")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("Synthetic sample data. Qloo is not being called.\n"))
        self.assertIn("calls: 14 of 30 used, 0 not spent; stopped because: done", out)
        trace = out.split("trace\n")[1].split("\nresult:")[0].splitlines()
        self.assertEqual(len(trace), 15)
        self.assertTrue(trace[0].lstrip().startswith("1  person look_up_favourite"))
        self.assertIn("/v2/insights synthetic", trace[9])
        self.assertTrue(trace[-1].endswith("every member is ranked"))
        self.assertIn("unrelated rankings would share about 3.1 of 50; this group shares", out)

    def test_it_runs_the_same_tools_in_the_same_order_as_the_page(self):
        _, out, _ = run("plan", SCENARIO, "--provider", "fake")
        steps = [line.split()[0] for line in out.split("steps\n")[1].split("trace\n")[0].splitlines()]
        self.assertEqual(steps, ["open_outing"] + ["look_up_favourite"] * 8 + ["look_up_kind"]
                         + ["resolve_match"] * 8 + ["change_conditions", "run_comparison"])

    def test_it_is_deterministic(self):
        once, twice = (run("plan", SCENARIO, "--provider", "fake") for _ in range(2))
        self.assertEqual(once, twice)

    def test_it_says_what_the_organiser_mode_does_on_the_organisers_behalf(self):
        _, out, _ = run("plan", SCENARIO, "--provider", "fake")
        self.assertIn("each favourite is Qloo's first candidate, recorded as resolved by the organiser", out)

    def test_as_the_agent_it_stops_where_only_a_person_may_act(self):
        code, out, err = run("plan", SCENARIO, "--provider", "fake", "--as", "agent")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("resolve_match m1 f1                      refused (not_a_tool)", out)
        self.assertIn("stopped: only a person can say which match was meant", out)
        self.assertNotIn("run_comparison", out)
        self.assertNotIn("result:", out)
        self.assertEqual({line.split()[1] for line in out.split("trace\n")[1].splitlines()}, {"agent"})

    def test_the_default_provider_without_a_key_is_the_fake(self):
        code, out, _ = run("plan", SCENARIO)
        self.assertEqual(code, 0)
        self.assertIn("Synthetic sample data", out)

    def test_a_scenario_that_cannot_be_read_is_refused_cleanly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as bad:
            bad.write("{not json")
        try:
            for path in ("/nowhere/at/all.json", bad.name):
                code, out, err = run("plan", path, "--provider", "fake")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("not a readable scenario file", err)
        finally:
            os.unlink(bad.name)


class PlanOnTheLiveSource(unittest.TestCase):
    def test_with_no_key_it_refuses_with_key_missing_and_sends_nothing(self):
        with mock.patch.object(wire, "send", side_effect=AssertionError("something was sent")) as sent:
            code, out, err = run("plan", SCENARIO, "--provider", "live")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("key: missing", err)
        sent.assert_not_called()

    def test_with_a_key_but_unverified_shapes_it_refuses_before_any_request(self):
        key = fake_key()
        with mock.patch.object(wire, "send", side_effect=AssertionError("something was sent")) as sent:
            code, out, err = run("plan", SCENARIO, "--provider", "live", environ={"QLOO_API_KEY": key})
        self.assertEqual(code, 2)
        self.assertIn("shapes_unverified", err)
        self.assertIn("refused (shapes_unverified)", out)
        self.assertNotIn(key, out + err)
        sent.assert_not_called()

    def test_a_provider_set_in_the_environment_is_refused_the_same_way(self):
        key = fake_key()
        code, out, err = run("plan", SCENARIO, environ={"QLOO_API_KEY": key})
        self.assertEqual(code, 2)
        self.assertIn("shapes_unverified", err)
        self.assertNotIn(key, out + err)

    def test_once_verified_it_walks_a_loopback_stand_in_and_the_key_stays_in_the_header(self):
        key = fake_key()
        with Stub(sources.FakeSource(), key) as stub, verified():
            code, out, err = run("plan", SCENARIO, "--provider", "live", "--base-url", stub.url,
                                 environ={"QLOO_API_KEY": key})
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Live: Qloo is being called (key: set)", out)
        self.assertIn("calls: 14 of 30 used, 0 not spent; stopped because: done", out)
        self.assertEqual(len(stub.requests), 14)
        self.assertTrue(all(r["headers"]["X-Api-Key"] == key and key not in r["path"] for r in stub.requests))
        self.assertNotIn(key, out)

    def test_a_base_url_that_is_not_qloos_is_refused_and_exits_two(self):
        key = fake_key()
        with verified():
            code, out, err = run("plan", SCENARIO, "--provider", "live", "--base-url", "https://example.com",
                                 environ={"QLOO_API_KEY": key})
        self.assertEqual(code, 2)
        self.assertIn("bad_base_url", err)
        self.assertNotIn(key, out + err)


class Budget(unittest.TestCase):
    def test_it_shows_the_limits_and_never_the_key(self):
        key = fake_key()
        code, out, err = run("budget", environ={"QLOO_API_KEY": key, "COMMON_GROUND_CALL_LIMIT": "40"})
        self.assertEqual((code, err), (0, ""))
        self.assertIn("key: set", out)
        self.assertIn("calls per outing: 40 (an organiser can lift it to 60)", out)
        self.assertIn("agent calls per workspace in 24 hours: 48", out)
        self.assertIn("server calls per UTC day: 300", out)
        self.assertIn("not a calendar day", out)
        self.assertNotIn(key, out)

    def test_without_a_key_it_says_missing(self):
        self.assertIn("key: missing", run("budget")[1])

    def test_with_a_scenario_it_counts_the_calls_it_would_make(self):
        _, out, _ = run("budget", SCENARIO)
        self.assertIn("at most 14 calls (8 searches, 1 tag search, 1 group search, 4 rankings)", out)
        self.assertIn("against the limit of 30: fits", out)
        _, small, _ = run("budget", SCENARIO, environ={"COMMON_GROUND_CALL_LIMIT": "10"})
        self.assertIn("needs the limit lifted to 14", small)

    def test_a_bad_setting_is_named_and_exits_two(self):
        code, out, err = run("budget", environ={"COMMON_GROUND_CALL_LIMIT": "999"})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("COMMON_GROUND_CALL_LIMIT", err)


class Stopper:
    """Stands in for the server: it records being asked to serve and to close, and can be interrupted."""

    server_address = ("127.0.0.1", 8761)

    def __init__(self, interrupt=False):
        self.interrupt, self.served, self.closed = interrupt, False, False

    def serve_forever(self):
        self.served = True
        if self.interrupt:
            raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


class Serve(unittest.TestCase):
    def serve(self, environ=None, interrupt=False):
        made = []
        stopper = Stopper(interrupt)

        def make(app, bind, port, *rest):
            made.append((bind, port))
            return stopper

        with mock.patch.object(cli.web, "make_server", make):
            code, out, err = run("serve", environ=environ)
        return code, out, err, made, stopper

    def test_it_serves_the_sample_data_and_says_where(self):
        code, out, err, made, stopper = self.serve()
        self.assertEqual((code, err, made), (0, "", [("127.0.0.1", 8761)]))
        self.assertTrue(out.startswith("Common Ground is running at http://127.0.0.1:8761/\n"))
        self.assertIn("Synthetic sample data. Qloo is not being called.", out)
        self.assertIn("go when the program stops", out)
        self.assertTrue(stopper.served and stopper.closed)

    def test_ctrl_c_ends_it_cleanly_and_closes_the_socket(self):
        code, _, err, _, stopper = self.serve(interrupt=True)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(stopper.closed)

    def test_the_port_a_host_injects_wins_and_a_host_bind_asks_for_https(self):
        environ = {"PORT": "10000", "COMMON_GROUND_PORT": "9000", "COMMON_GROUND_BIND": "0.0.0.0",
                   "RENDER_EXTERNAL_HOSTNAME": "demo.example"}
        code, out, _, made, _ = self.serve(environ)
        self.assertEqual((code, made), (0, [("0.0.0.0", 10000)]))
        self.assertIn("reach it through the host's HTTPS address", out)
        self.assertNotIn("http://", out)

    def test_a_bind_beyond_this_machine_with_no_allowed_host_exits_two_naming_the_setting(self):
        code, out, err, made, _ = self.serve({"COMMON_GROUND_BIND": "0.0.0.0"})
        self.assertEqual((code, out, made), (2, "", []))
        self.assertIn("COMMON_GROUND_ALLOWED_HOSTS", err)

    def test_live_without_a_key_is_refused_and_serves_nothing(self):
        code, out, err, made, _ = self.serve({"COMMON_GROUND_PROVIDER": "live"})
        self.assertEqual((code, out, made), (2, "", []))
        self.assertIn("key: missing", err)

    def test_live_with_a_key_says_so_and_that_shapes_are_unchecked_and_prints_no_key(self):
        key = fake_key()
        code, out, err, made, _ = self.serve({"QLOO_API_KEY": key})
        self.assertEqual((code, made), (0, [("127.0.0.1", 8761)]))
        self.assertIn("Live: Qloo is being called (key: set)", out)
        self.assertIn("shapes_unverified", out)
        self.assertNotIn(key, out + err)

    def test_a_bad_setting_is_named(self):
        code, out, err, made, _ = self.serve({"PORT": "not-a-port"})
        self.assertEqual((code, out, made), (2, "", []))
        self.assertIn("PORT", err)


if __name__ == "__main__":
    unittest.main()
