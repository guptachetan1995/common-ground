"""The rig for the browser walks builds every case offline, and its proxy strips the browser's labels."""
import http.client
import json
import unittest

from common_ground import measured
from tests import browser_rig
from tests.served import Served
from tests.session import Session


class Cases(unittest.TestCase):
    def test_every_case_builds_a_gateway_with_a_source_and_no_network(self):
        before = measured.UNVERIFIED
        self.addCleanup(setattr, measured, "UNVERIFIED", before)
        for name, build in browser_rig.CASES.items():
            with self.subTest(name):
                built = build()
                self.assertIn(built.new_outing_source(), ("live", "synthetic"))

    def test_the_ceiling_cases_keep_a_sample_source_beside_a_live_one(self):
        before = measured.UNVERIFIED
        self.addCleanup(setattr, measured, "UNVERIFIED", before)
        for name in ("ceiling_soon", "ceiling_spent", "qloo_down"):
            with self.subTest(name):
                built = browser_rig.CASES[name]()
                self.assertTrue(built.source.live)
                self.assertIsNotNone(built.sample)


class Proxy(unittest.TestCase):
    def test_a_browser_behind_it_sends_no_label_and_is_told_so(self):
        with Served(Session()) as served:
            proxy = browser_rig.start_proxy(served.port)
            self.addCleanup(proxy.server_close)
            self.addCleanup(proxy.shutdown)
            port = proxy.server_address[1]

            def get(path, headers):
                link = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                link.request("GET", path, headers=headers)
                answer = link.getresponse()
                return answer.status, dict(answer.getheaders()), answer.read()

            status, headers, _ = get("/", {"Sec-Fetch-Site": "none"})
            self.assertEqual(status, 200)
            cookie = headers["Set-Cookie"].split(";")[0]
            status, _, body = get("/api/state", {"Cookie": cookie, "Sec-Fetch-Site": "same-origin"})
            state = json.loads(body)
            self.assertEqual((status, state["actor"], state["actorWhy"]), (200, "agent", "no_fetch_metadata"))


if __name__ == "__main__":
    unittest.main()
