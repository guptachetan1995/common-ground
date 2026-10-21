import unittest
from unittest import mock

from common_ground import qloo_calls, records, sources, wire
from common_ground.refusal import Refusal
from tests import NetworkBlocked
from tests.support import Canned, Stub, conditions, fake_key


def search(name="Dune"):
    return qloo_calls.search_request(name)


def asked(stub, request, key=None, **kwargs):
    return wire.send(request, key or stub.key, base_url=stub.url, **kwargs)


def outcome(stub, request, key=None, **kwargs):
    try:
        asked(stub, request, key, **kwargs)
    except Refusal as error:
        return error
    raise AssertionError("no refusal")


class Sending(unittest.TestCase):
    def test_a_get_with_the_key_in_one_header_and_nowhere_else(self):
        key = fake_key()
        with Stub(sources.FakeSource(), key) as stub:
            reply = asked(stub, search("Khruangbin"), key)
        self.assertEqual(reply.status, 200)
        self.assertIsInstance(reply.ms, int)
        self.assertEqual(len(records.read_search(reply.body).candidates), 5)
        (seen,) = stub.requests
        self.assertEqual(seen["command"], "GET")
        self.assertEqual(seen["headers"]["X-Api-Key"], key)
        self.assertNotIn(key, seen["path"])
        self.assertEqual(seen["path"], "/search?" + search("Khruangbin").query_string())
        elsewhere = [n for n, value in seen["headers"].items() if key in value and n != "X-Api-Key"]
        self.assertFalse(elsewhere)

    def test_the_request_has_no_body_and_asks_for_json(self):
        key = fake_key()
        with Stub(sources.FakeSource(), key) as stub:
            asked(stub, search(), key)
        headers = stub.requests[0]["headers"]
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("Content-Length", headers)

    def test_one_attempt_only(self):
        key = fake_key()
        with Stub(Canned(503, {"error": "busy"}), key) as stub:
            outcome(stub, search(), key)
        self.assertEqual(len(stub.requests), 1)


class Naming(unittest.TestCase):
    cases = {
        400: "qloo_bad_request", 401: "qloo_auth", 403: "qloo_unsupported_type", 404: "qloo_bad_request",
        418: "qloo_bad_request", 429: "qloo_rate_limited", 500: "qloo_unavailable", 503: "qloo_unavailable",
    }

    def test_each_status_has_its_name_and_carries_the_status(self):
        key = fake_key()
        for status, name in self.cases.items():
            with self.subTest(status=status), Stub(Canned(status, {"error": {"message": "x"}}), key) as stub:
                error = outcome(stub, search(), key)
                self.assertIsInstance(error, wire.QlooError)
                self.assertEqual((error.code, error.status), (name, status))
                self.assertEqual(wire.outcome_for(status), name)

    def test_the_error_body_is_known_by_its_shape_only(self):
        key = fake_key()
        with Stub(Canned(400, {"error": {"message": "secret words", "code": 7}}), key) as stub:
            error = outcome(stub, search(), key)
        self.assertEqual(error.shape, {
            "$": ("object", 1), "$.error": ("object", 1), "$.error.message": ("string", 1),
            "$.error.code": ("number", 1),
        })
        self.assertNotIn("secret", repr(error.shape) + str(error) + repr(error) + error.detail)

    def test_an_error_body_that_is_not_json_has_no_shape(self):
        key = fake_key()
        with Stub(Canned(502, b"<html>bad gateway</html>"), key) as stub:
            error = outcome(stub, search(), key)
        self.assertEqual((error.code, error.shape), ("qloo_unavailable", {}))

    def test_an_empty_200_is_no_results_and_not_a_failure_of_the_wire(self):
        key = fake_key()
        for body in (b"", b"  \n"):
            with self.subTest(body=body), Stub(Canned(200, body), key) as stub:
                error = outcome(stub, search(), key)
                self.assertEqual((error.code, error.status), ("qloo_no_results", 200))

    def test_a_200_that_is_not_json_is_an_unexpected_shape(self):
        key = fake_key()
        with Stub(Canned(200, b"not json at all"), key) as stub:
            error = outcome(stub, search(), key)
        self.assertEqual((error.code, error.detail), ("qloo_unexpected_shape", "$"))

    def test_a_body_over_the_cap_is_refused(self):
        key = fake_key()
        with mock.patch.object(wire, "MAX_BODY", 20), Stub(Canned(200, {"results": ["x" * 40]}), key) as stub:
            self.assertEqual(outcome(stub, search(), key).code, "qloo_unexpected_shape")

    def test_a_server_that_is_not_there(self):
        key = fake_key()
        with Stub(Canned(200, {}), key) as stub:
            url = stub.url
        with self.assertRaises(wire.QlooError) as caught:
            wire.send(search(), key, base_url=url)
        self.assertEqual((caught.exception.code, caught.exception.status), ("qloo_unavailable", 0))

    def test_a_slow_server_times_out(self):
        key = fake_key()
        with Stub(Canned(200, {"results": []}), key, delay=0.5) as stub:
            self.assertEqual(outcome(stub, search(), key, timeout=0.05).code, "qloo_unavailable")


class KeyHygiene(unittest.TestCase):
    def test_a_401_that_echoes_the_key_leaks_it_nowhere(self):
        real, wrong = fake_key(), fake_key()
        with Stub(sources.FakeSource(), real, echo_key_in_errors=True) as stub:
            error = outcome(stub, search(), wrong)
        self.assertEqual(error.code, "qloo_auth")
        for rendering in (str(error), repr(error), error.detail, repr(error.shape), repr(error.args)):
            self.assertNotIn(wrong, rendering)
        self.assertTrue(any(wrong in r["headers"].get("X-Api-Key", "") for r in stub.requests))

    def test_a_connection_error_leaks_neither_key_nor_url(self):
        key = fake_key()
        leaky = OSError(f"failed for {key} at /search?query=Dune")
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=leaky):
            with self.assertRaises(wire.QlooError) as caught:
                wire.send(search("Dune"), key, base_url="http://127.0.0.1:9")
        error = caught.exception
        for rendering in (str(error), repr(error), error.detail, repr(error.args)):
            self.assertNotIn(key, rendering)
            self.assertNotIn("Dune", rendering)
        self.assertTrue(error.__suppress_context__)

    def test_a_redirect_is_not_followed_and_carries_no_key_anywhere(self):
        key = fake_key()
        with Stub(Canned(200, {}), key) as elsewhere:
            with Stub(Canned(302, {}, {"Location": elsewhere.url + "/search"}), key) as stub:
                error = outcome(stub, search(), key)
        self.assertEqual((error.code, error.status), ("qloo_unavailable", 302))
        self.assertEqual(elsewhere.requests, [])

    def test_the_key_only_goes_to_the_hackathon_host_or_a_loopback_stub(self):
        key = fake_key()
        for url in (
            "https://example.com", "http://example.com", "https://hackathon.api.qloo.com.evil.example",
            "http://hackathon.api.qloo.com", "ftp://127.0.0.1", "http://192.0.2.1:80", "https://127.0.0.1:9",
        ):
            with self.subTest(url=url):
                with self.assertRaises(Refusal) as caught:
                    wire.send(search(), key, base_url=url)
                self.assertEqual(caught.exception.code, "bad_base_url")

    def test_loopback_names_are_accepted_but_never_reach_the_network(self):
        key = fake_key()
        for url in ("http://127.0.0.1:9", "http://localhost:9", "http://[::1]:9"):
            with self.subTest(url=url):
                with self.assertRaises(wire.QlooError) as caught:
                    wire.send(search(), key, base_url=url, timeout=0.5)
                self.assertEqual(caught.exception.code, "qloo_unavailable")

    def test_the_real_host_is_reached_only_through_the_tests_network_guard(self):
        with self.assertRaises(NetworkBlocked):
            wire.send(search(), fake_key())

    def test_the_header_name_and_base_url_are_the_documented_ones(self):
        self.assertEqual((wire.KEY_HEADER, wire.BASE_URL), ("X-Api-Key", "https://hackathon.api.qloo.com"))


class FakeSourceAgreesWithTheWire(unittest.TestCase):
    def test_a_full_group_search_over_the_socket_reads_back_the_same(self):
        key = fake_key()
        request = qloo_calls.group_search_request(conditions(placeText="New York City"), ["a", "b"])
        direct = sources.FakeSource().fetch(request).body
        with Stub(sources.FakeSource(), key) as stub:
            over = asked(stub, request, key).body
        self.assertEqual(over, direct)


if __name__ == "__main__":
    unittest.main()
