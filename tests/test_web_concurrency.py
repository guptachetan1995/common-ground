"""Two outings at once, over a socket, against a stand-in for Qloo that is slow: no request waits for
another workspace's network call, the limits stay exact however the calls interleave, and the server never
runs more handler threads than it was given."""
import socket
import threading
import time
import unittest

from common_ground import wire
from tests.served import Browser, Served, sample_walk
from tests.session import Transport, live_session, verified


class Slow(Transport):
    """A stand-in for the network: it counts calls in flight, can sleep, can hold each call until it is
    released, and can make every workspace's group search meet the others at a barrier."""

    def __init__(self, delay=0.0, barrier=None):
        super().__init__()
        self.delay, self.barrier = delay, barrier
        self.hold = False
        self.release = threading.Semaphore(0)
        self.lock = threading.Lock()
        self.in_flight = self.peak = self.calls = 0

    def __call__(self, request, key, base_url=wire.BASE_URL):
        with self.lock:
            self.in_flight += 1
            self.calls += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            if self.barrier and self.is_group_search(request):
                self.barrier.wait(timeout=10)
            if self.hold:
                assert self.release.acquire(timeout=10), "a held call was never released"
            time.sleep(self.delay)
            return super().__call__(request, key, base_url)
        finally:
            with self.lock:
                self.in_flight -= 1

    @staticmethod
    def is_group_search(request):
        return request.path == "/v2/insights" and "filter.results.entities" not in request.as_dict()

    def wait_for(self, in_flight=None, calls=None, seconds=5.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if (in_flight is None or self.in_flight == in_flight) and (calls is None or self.calls >= calls):
                return
            time.sleep(0.005)
        raise AssertionError(f"{self.in_flight} calls in flight and {self.calls} made")


def outing_args(tag, members=2, favourites=4):
    return {
        "label": f"Outing {tag}", "place_text": "New York City", "day": "friday",
        "price_min": 2, "price_max": 3,
        "members": [
            {"name": f"P{n}", "favourites": [f"{tag} favourite {n}.{k}" for k in range(favourites)][:3]}
            for n in range(members)
        ],
    }


def run_in_threads(jobs):
    errors = []

    def guard(job):
        try:
            job()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=guard, args=(job,), daemon=True) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    if errors:
        raise errors[0]


class Concurrency(unittest.TestCase):
    def serve(self, transport, ceiling=1000, **config):
        patch = verified()
        patch.start()
        self.addCleanup(patch.stop)
        session = live_session(transport, ceiling=ceiling, **config)
        served = Served(session)
        served.__enter__()
        self.addCleanup(served.__exit__, None, None, None)
        return served

    def search_all(self, browser, outing_id, out=None, every=(0, 1)):
        """One search per favourite of the outing, or of every n-th favourite, as the page's script would."""
        outcomes = out if out is not None else []
        outing = next(o for o in browser.state()["outings"] if o["id"] == outing_id)
        pairs = [(m["id"], f["id"]) for m in outing["members"] for f in m["favourites"]]
        for member_id, favourite_id in pairs[every[0]::every[1]]:
            outcomes.append(browser.act("look_up_favourite", {
                "outing_id": outing_id, "member_id": member_id, "favourite_id": favourite_id})["outcome"])
        return outcomes

    def test_two_workspaces_make_their_qloo_calls_at_the_same_time(self):
        barrier = threading.Barrier(2)
        transport = Slow(delay=0.01, barrier=barrier)
        served = self.serve(transport)
        one, two = Browser(served), Browser(served)

        def walk(browser, city):
            browser.open()
            args = {**browser.get("/api/sample").json["args"], "place_text": city}
            outing = browser.ok("open_outing", args)["outingId"]
            self.search_all(browser, outing)
            tags = browser.ok("look_up_kind", {"outing_id": outing, "query": "restaurant"})["tags"]
            for member in browser.state()["outings"][-1]["members"]:
                for favourite in member["favourites"]:
                    browser.ok("resolve_match", {"outing_id": outing, "member_id": member["id"],
                                                 "favourite_id": favourite["id"],
                                                 "entity_id": favourite["candidates"][0]["entityId"]})
            browser.ok("change_conditions", {"outing_id": outing, "kind_tag": tags[0]["id"]})
            result = browser.ok("run_comparison", {"outing_id": outing})
            self.assertIn(result["outcome"], ("common", "none_shared"))

        run_in_threads([lambda: walk(one, "New York City"), lambda: walk(two, "Los Angeles")])
        self.assertFalse(barrier.broken)
        self.assertGreaterEqual(transport.peak, 2)

    def test_the_server_ceiling_is_exact_when_outings_race_for_it(self):
        transport = Slow(delay=0.005)
        served = self.serve(transport, ceiling=10)
        one, two = Browser(served), Browser(served)
        ids = {}
        for name, browser in (("one", one), ("two", two)):
            browser.open()
            ids[name] = browser.ok("open_outing", outing_args(name))["outingId"]
        outcomes = []
        run_in_threads([lambda: self.search_all(one, ids["one"], outcomes),
                        lambda: self.search_all(two, ids["two"], outcomes)])
        self.assertEqual(len(outcomes), 12)
        self.assertEqual(transport.calls, 10)
        self.assertEqual(served.session.source.ledger.used(), 10)
        self.assertEqual(outcomes.count("ok"), 10)
        self.assertEqual(outcomes.count("daily_ceiling_spent"), 2)

    def test_an_outings_call_limit_is_exact_when_requests_race_for_it(self):
        transport = Slow(delay=0.005)
        served = self.serve(transport, call_limit=4)
        browser = Browser(served)
        browser.open()
        outing = browser.ok("open_outing", outing_args("solo", members=3, favourites=3))["outingId"]
        outcomes = []
        run_in_threads([lambda k=k: self.search_all(browser, outing, outcomes, (k, 3)) for k in range(3)])
        self.assertEqual(transport.calls, 4)
        self.assertEqual(outcomes.count("ok"), 4)
        self.assertEqual(outcomes.count("over_limit"), len(outcomes) - 4)
        self.assertEqual(browser.state()["outings"][-1]["budget"]["spent"], 4)

    def test_two_outings_in_one_workspace_each_keep_their_own_limit(self):
        transport = Slow(delay=0.002)
        served = self.serve(transport, call_limit=3)
        browser = Browser(served)
        browser.open()
        first = browser.ok("open_outing", outing_args("first", members=2, favourites=3))["outingId"]
        second = browser.ok("open_outing", outing_args("second", members=2, favourites=3))["outingId"]
        outcomes = {first: [], second: []}
        run_in_threads([lambda: self.search_all(browser, first, outcomes[first]),
                        lambda: self.search_all(browser, second, outcomes[second])])
        self.assertEqual(transport.calls, 6)
        for outing in (first, second):
            self.assertEqual(outcomes[outing].count("ok"), 3)

    def test_the_agents_allowance_is_exact_across_outings_and_a_person_is_not_held_to_it(self):
        transport = Slow(delay=0.002)
        served = self.serve(transport, agent_calls_per_day=5)
        browser = Browser(served)
        browser.open()
        address = browser.state()["agentAddress"]
        token = address.rsplit("/", 1)[1]
        made = [browser.ok("open_outing", outing_args(n, members=2, favourites=3))["outingId"]
                for n in ("a", "b", "c")]
        outcomes = []

        def agent_searches(outing_id):
            outing = next(o for o in browser.state()["outings"] if o["id"] == outing_id)
            for member in outing["members"]:
                for favourite in member["favourites"]:
                    asked = {"outing_id": outing_id, "member_id": member["id"],
                             "favourite_id": favourite["id"]}
                    reply = served.call("POST", f"/agent/{token}/dispatch",
                                        {"tool": "look_up_favourite", "args": asked})
                    outcomes.append(reply.json["outcome"])

        run_in_threads([lambda: agent_searches(made[0]), lambda: agent_searches(made[1])])
        self.assertEqual(transport.calls, 5)
        self.assertEqual(outcomes.count("ok"), 5)
        self.assertEqual(outcomes.count("agent_allowance_spent"), 7)
        by_person = self.search_all(browser, made[2])
        self.assertEqual(by_person, ["ok"] * 6)
        self.assertEqual(transport.calls, 11)

    def test_the_state_and_the_call_strip_answer_while_a_comparison_is_in_flight(self):
        transport = Slow()
        served = self.serve(transport)
        browser = Browser(served)
        outing = sample_walk(browser, compare=False)
        before = len(browser.get("/api/calls").json["calls"])
        made = transport.calls
        transport.hold = True
        finished = []
        compare = lambda: finished.append(browser.ok("run_comparison", {"outing_id": outing}))
        worker = threading.Thread(target=compare, daemon=True)
        worker.start()
        transport.wait_for(1, made + 1)
        started = time.monotonic()
        self.assertEqual(browser.get("/api/state").status, 200)
        self.assertEqual(browser.get("/api/calls").status, 200)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(len(browser.get("/api/calls").json["calls"]), before)
        transport.release.release()
        transport.wait_for(calls=made + 2)
        self.assertEqual(len(browser.get("/api/calls").json["calls"]), before + 1)
        for _ in range(8):
            transport.release.release()
        worker.join(15)
        self.assertEqual(len(finished), 1)

    def test_a_workspace_waiting_on_its_own_comparison_does_not_hold_up_another(self):
        transport = Slow()
        served = self.serve(transport)
        slow, other = Browser(served), Browser(served)
        outing = sample_walk(slow, compare=False)
        made = transport.calls
        transport.hold = True
        compare = lambda: slow.ok("run_comparison", {"outing_id": outing})
        worker = threading.Thread(target=compare, daemon=True)
        worker.start()
        transport.wait_for(1, made + 1)
        started = time.monotonic()
        other.open()
        made = other.ok("open_outing", outing_args("quick"))
        self.assertEqual(made["outingId"], "out_001")
        self.assertEqual(other.act("spend_report")["outcome"], "ok")
        self.assertLess(time.monotonic() - started, 2.0)
        transport.hold = False
        for _ in range(20):
            transport.release.release()
        worker.join(15)


class ThreadCap(unittest.TestCase):
    def held(self, served, n):
        sockets = []
        for _ in range(n):
            s = socket.create_connection(("127.0.0.1", served.port), timeout=10)
            s.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n")
            sockets.append(s)
        return sockets

    def test_beyond_the_cap_a_request_is_answered_503_at_once_and_the_slots_come_back(self):
        with Served(max_threads=2) as served:
            holders = self.held(served, 2)
            time.sleep(0.2)
            started = time.monotonic()
            busy = served.call("GET", "/healthz")
            self.assertEqual((busy.status, busy.json["outcome"]), (503, "busy"))
            self.assertEqual(busy.headers["retry-after"], "1")
            self.assertLess(time.monotonic() - started, 2.0)
            for s in holders:
                s.close()
            end = time.monotonic() + 5
            while time.monotonic() < end and served.call("GET", "/healthz").status != 200:
                time.sleep(0.02)
            self.assertEqual(served.call("GET", "/healthz").status, 200)
            self.assertEqual(served.call("GET", "/healthz").status, 200)
            self.assertEqual(served.call("GET", "/healthz").status, 200)

    def test_a_turned_away_request_does_not_leak_a_slot(self):
        with Served(max_threads=1) as served:
            for _ in range(5):
                holder = self.held(served, 1)
                time.sleep(0.1)
                self.assertEqual(served.call("GET", "/healthz").status, 503)
                self.assertEqual(served.call("GET", "/healthz").status, 503)
                holder[0].close()
                end = time.monotonic() + 5
                while time.monotonic() < end and served.call("GET", "/healthz").status != 200:
                    time.sleep(0.02)
            self.assertEqual(served.call("GET", "/healthz").status, 200)

    def test_requests_held_inside_a_qloo_call_count_against_the_cap(self):
        transport = Slow()
        patch = verified()
        patch.start()
        self.addCleanup(patch.stop)
        session = live_session(transport)
        with Served(session, max_threads=2) as served:
            one, two = Browser(served), Browser(served)
            ids = {}
            for name, browser in (("one", one), ("two", two)):
                browser.open()
                ids[name] = browser.ok("open_outing", outing_args(name))["outingId"]
            transport.hold = True
            threads = [
                threading.Thread(target=lambda b=b, i=i: b.act("look_up_favourite", {
                    "outing_id": i, "member_id": "m1", "favourite_id": "f1"}), daemon=True)
                for b, i in ((one, ids["one"]), (two, ids["two"]))
            ]
            for t in threads:
                t.start()
            transport.wait_for(2)
            busy = served.call("GET", "/healthz")
            self.assertEqual((busy.status, busy.json["outcome"]), (503, "busy"))
            for _ in range(2):
                transport.release.release()
            for t in threads:
                t.join(10)
            end = time.monotonic() + 5
            while time.monotonic() < end and served.call("GET", "/healthz").status != 200:
                time.sleep(0.02)
            self.assertEqual(served.call("GET", "/healthz").status, 200)


if __name__ == "__main__":
    unittest.main()
