import re
import socket
import unittest
from unittest import mock

from common_ground import fair_share, measured, qloo_calls, records, settings, sources, wire
from common_ground.refusal import Refusal
from tests.session import Clock, Transport, verified
from tests.support import RESERVED, Canned, Stub, conditions, fake_key, strings_in

KIND = {"id": "urn:tag:synthetic:restaurant", "name": "Restaurant"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def nyc(**changes):
    return conditions(**{"placeText": "New York City", **changes})


def group(source, **changes):
    request = qloo_calls.group_search_request(nyc(**changes), ["x1", "x2"])
    return records.read_group_search(source.fetch(request).body)


def search(source, name):
    return records.read_search(source.fetch(qloo_calls.search_request(name)).body)


class Search(unittest.TestCase):
    def test_any_favourite_gets_up_to_five_invented_candidates(self):
        found = search(sources.FakeSource(), "Khruangbin")
        self.assertEqual(len(found.candidates), 5)
        self.assertEqual(found.candidates[0].name, "Khruangbin")
        self.assertEqual(len({c.entity_id for c in found.candidates}), 5)
        self.assertTrue(all(c.disambiguation == sources.SYNTHETIC_NOTE for c in found.candidates))
        self.assertTrue(all(c.entity_id.startswith(RESERVED) for c in found.candidates))
        self.assertNotIn("urn:entity:person", {c.type for c in found.candidates})

    def test_the_same_name_gives_the_same_answer_whatever_the_case(self):
        a, b = search(sources.FakeSource(), "Dune"), search(sources.FakeSource(), "dune")
        self.assertEqual([c.entity_id for c in a.candidates], [c.entity_id for c in b.candidates])

    def test_different_names_give_different_ids(self):
        fake = sources.FakeSource()
        one = {c.entity_id for c in search(fake, "Dune").candidates}
        two = {c.entity_id for c in search(fake, "The Bear").candidates}
        self.assertFalse(one & two)

    def test_take_and_types_are_honoured(self):
        fake = sources.FakeSource()
        one = records.read_search(fake.fetch(qloo_calls.search_request("Dune", take=1)).body)
        self.assertEqual(len(one.candidates), 1)
        types = set(measured.FAVOURITE_TYPES)
        self.assertTrue({c.type for c in search(fake, "Dune").candidates} <= types)
        asked = [("query", "Dune"), ("types", "urn:entity:person"), ("take", "5")]
        status, body = fake.respond("/search", asked)
        self.assertNotIn("urn:entity:person", {r["type"] for r in body["results"]})

    def test_the_candidate_type_order_can_be_set_by_a_subclass(self):
        class Bands(sources.FakeSource):
            def candidate_type_order(self, text, types):
                return ["urn:entity:artist"] + [t for t in types if t != "urn:entity:artist"]

        self.assertEqual(search(Bands(), "Anything").candidates[0].type, "urn:entity:artist")


class Tags(unittest.TestCase):
    def test_restaurant(self):
        tags = records.read_tags(sources.FakeSource().fetch(qloo_calls.tags_request("restaurant")).body)
        self.assertEqual([t.name for t in tags], ["Restaurant", "Fast Food Restaurant"])
        self.assertTrue(all(t.id.startswith("urn:tag:synthetic:") for t in tags))

    def test_nothing_matches(self):
        with self.assertRaises(Refusal) as caught:
            records.read_tags(sources.FakeSource().fetch(qloo_calls.tags_request("zzzz")).body)
        self.assertEqual(caught.exception.code, "qloo_no_results")


class GroupSearch(unittest.TestCase):
    def test_the_sample_conditions_fill_the_long_list(self):
        found = group(sources.FakeSource(), kindTag=KIND)
        self.assertEqual(len(found.places), 50)
        self.assertTrue(all(p.entity_id.startswith(RESERVED) for p in found.places))
        self.assertEqual(len({p.entity_id for p in found.places}), 50)
        self.assertTrue(all(any(t.id == KIND["id"] for t in p.tags) for p in found.places))

    def test_the_second_city_also_passes_the_probes_rule(self):
        found = group(sources.FakeSource(), placeText="Los Angeles", kindTag=KIND)
        self.assertGreaterEqual(len(found.places), 30)
        self.assertTrue(all("Los Angeles" in p.address for p in found.places))

    def test_each_condition_changes_the_result(self):
        fake = sources.FakeSource()
        ids = lambda found: {p.entity_id for p in found.places}  # noqa: E731
        base = ids(group(fake, kindTag=KIND))
        for name, changes in (("location", {"placeText": "Los Angeles"}), ("day", {"day": "sunday"}),
                              ("price", {"priceMin": 1, "priceMax": 1}), ("kind", {"kindTag": None})):
            with self.subTest(name):
                self.assertNotEqual(ids(group(fake, **{"kindTag": KIND, **changes})), base)

    def test_a_place_closed_that_day_is_not_returned(self):
        fake = sources.FakeSource()
        closed = {p["entity_id"] for p in fake.catalogue if p["closed"] == "friday"}
        found = group(fake, kindTag=KIND)
        self.assertFalse({p.entity_id for p in found.places} & closed)

    def test_take_is_capped_at_fifty_and_defaults_to_twenty(self):
        fake = sources.FakeSource()
        status, body = fake.respond("/v2/insights", [("filter.type", qloo_calls.PLACE)])
        self.assertEqual(len(body["results"]["entities"]), 20)
        status, body = fake.respond("/v2/insights", [("filter.type", qloo_calls.PLACE), ("take", "500")])
        self.assertEqual(len(body["results"]["entities"]), 50)

    def test_excluded_ids_do_not_come_back(self):
        fake = sources.FakeSource()
        first = group(fake, kindTag=KIND).places[0].entity_id
        base = qloo_calls.group_search_request(nyc(), ["x1"])
        request = qloo_calls.add_param(base, "filter.exclude.entities", first)
        returned = records.read_group_search(fake.fetch(request).body).places
        self.assertNotIn(first, [p.entity_id for p in returned])

    def test_affinity_explainability_and_the_aggregate(self):
        fake = sources.FakeSource()
        request = qloo_calls.group_search_request(nyc(), ["x1", "x2"])
        body = fake.fetch(request).body
        skel = records.skeleton(body)
        self.assertEqual(skel["$.results.entities[].query.affinity"][1], 50)
        self.assertEqual(skel["$.results.entities[].query.explainability"][1], 50)
        self.assertIn("$.query.explainability", skel)
        self.assertIn("$.query.locality.signal", skel)
        self.assertEqual(sorted(records.read_group_search(body).influence), ["x1", "x2"])

    def test_without_explainability_or_affinity(self):
        request = qloo_calls.group_search_request(nyc(), ["x1"])
        body = sources.FakeSource(with_explainability=False, with_affinity=False).fetch(request).body
        skel = records.skeleton(body)
        self.assertFalse([p for p in skel if "explainability" in p or "affinity" in p])
        self.assertIsNone(records.read_group_search(body).influence)

    def test_explainability_is_only_sent_when_asked_for(self):
        asked = [("filter.type", qloo_calls.PLACE), ("signal.interests.entities", "x1")]
        status, body = sources.FakeSource().respond("/v2/insights", asked)
        self.assertFalse([p for p in records.skeleton(body) if "explainability" in p])


class Ranking(unittest.TestCase):
    def long_list(self, fake):
        return [p.entity_id for p in group(fake, kindTag=KIND).places]

    def rank(self, fake, member_ids, long_list):
        request = qloo_calls.ranking_request(nyc(), member_ids, long_list)
        return records.read_ranking(fake.fetch(request).body, long_list)

    def test_every_requested_id_comes_back_in_the_members_own_order(self):
        fake = sources.FakeSource()
        ids = self.long_list(fake)
        ranking = self.rank(fake, ["a", "b"], ids)
        self.assertEqual(sorted(r.entity_id for r in ranking.ranked), sorted(ids))
        self.assertEqual(
            (ranking.returned_share, ranking.unrequested, ranking.non_increasing), (1.0, 0, True)
        )
        self.assertTrue(all(r.affinity is not None and r.because for r in ranking.ranked))

    def test_different_favourites_rank_the_same_places_differently(self):
        fake = sources.FakeSource()
        ids = self.long_list(fake)
        one, two = self.rank(fake, ["a"], ids), self.rank(fake, ["b"], ids)
        self.assertNotEqual([r.entity_id for r in one.ranked], [r.entity_id for r in two.ranked])
        only_in_one = fair_share.upper_half_ids(one, 50) - fair_share.upper_half_ids(two, 50)
        self.assertGreaterEqual(len(only_in_one), 3)

    def test_the_same_favourite_ranks_the_same_way_each_time(self):
        fake = sources.FakeSource()
        ids = self.long_list(fake)
        self.assertEqual(self.rank(fake, ["a"], ids), self.rank(sources.FakeSource(), ["a"], ids))

    def test_the_group_search_leans_toward_what_everyone_named(self):
        fake = sources.FakeSource()
        body = fake.fetch(qloo_calls.group_search_request(nyc(), ["a", "b"])).body
        affinities = [p["query"]["affinity"] for p in body["results"]["entities"]]
        self.assertEqual(affinities, sorted(affinities, reverse=True))

    def test_a_ranking_covers_only_what_was_asked(self):
        fake = sources.FakeSource()
        ids = self.long_list(fake)[:12]
        self.assertEqual(len(self.rank(fake, ["a"], ids).ranked), 12)

    def test_forward_and_reverse_tastes_give_opposite_orders(self):
        fake = sources.FakeSource(tastes={"first": "forward", "second": "reverse"})
        first = search(fake, "First").candidates[0].entity_id
        second = search(fake, "Second").candidates[0].entity_id
        ids = self.long_list(fake)
        forward, backward = self.rank(fake, [first], ids), self.rank(fake, [second], ids)
        order = [r.entity_id for r in backward.ranked]
        self.assertEqual([r.entity_id for r in forward.ranked], list(reversed(order)))

    def test_without_affinity_the_order_is_still_returned(self):
        fake = sources.FakeSource(with_affinity=False)
        ids = self.long_list(fake)
        ranking = self.rank(fake, ["a"], ids)
        self.assertTrue(all(r.affinity is None for r in ranking.ranked))
        self.assertEqual(len(ranking.ranked), len(ids))


class Everywhere(unittest.TestCase):
    def test_nothing_invented_looks_like_a_real_id(self):
        fake = sources.FakeSource()
        bodies = [
            fake.fetch(qloo_calls.search_request("Dune")).body,
            fake.fetch(qloo_calls.tags_request("bar")).body,
            fake.fetch(qloo_calls.group_search_request(nyc(), ["a"])).body,
        ]
        seen = [s for body in bodies for s in strings_in(body) if UUID.fullmatch(s)]
        self.assertTrue(seen)
        self.assertTrue(all(s.startswith(RESERVED) for s in seen))

    def test_fake_never_touches_the_network(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("a socket was opened")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("a lookup was made")):
            fake = sources.FakeSource()
            fake.fetch(qloo_calls.search_request("Dune"))
            fake.fetch(qloo_calls.group_search_request(nyc(), ["a"]))

    def test_an_unsupported_type_is_a_403_and_an_unknown_route_a_404(self):
        fake = sources.FakeSource()
        with self.assertRaises(wire.QlooError) as caught:
            fake.fetch(qloo_calls.unsupported_type_request())
        self.assertEqual((caught.exception.code, caught.exception.status), ("qloo_unsupported_type", 403))
        self.assertIn("$.error.message", caught.exception.shape)
        self.assertEqual(fake.respond("/v2/trending", [])[0], 404)

    def test_the_fake_has_a_name_for_the_banner(self):
        self.assertEqual(sources.FakeSource.name, "fake")


class Tally:
    """A meter that remembers what it was told, and refuses once `limit` requests have been recorded."""

    def __init__(self, limit=None):
        self.limit = limit
        self.admitted = []
        self.rows = []

    def admit(self, live):
        if self.limit is not None and len([r for r in self.rows if r[1] != "cache"]) >= self.limit:
            raise Refusal("over_limit", "tally")
        self.admitted.append(live)

    def record(self, path, cache, ms, live):
        self.rows.append((path, cache, ms, live))


def live(transport=None, clock=None, ceiling=100, ttl=60, key=None):
    clock = clock or Clock()
    transport = transport or Transport()
    source = sources.LiveSource(
        key or fake_key(), daily_ceiling=ceiling, cache_ttl_s=ttl,
        send=transport, clock=clock, sleep=clock.sleep,
    )
    return source, transport, clock


class FakeWithAMeter(unittest.TestCase):
    def test_the_meter_is_asked_first_and_told_afterwards_without_a_live_call(self):
        tally = Tally()
        sources.FakeSource().fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(tally.admitted, [False])
        self.assertEqual(tally.rows, [("/search", "synthetic", 0, False)])

    def test_a_refusal_from_the_meter_stops_the_request(self):
        tally = Tally(limit=0)
        with self.assertRaises(Refusal) as caught:
            sources.FakeSource().fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(caught.exception.code, "over_limit")
        self.assertEqual(tally.rows, [])

    def test_an_error_answer_is_still_a_counted_call(self):
        tally = Tally()
        with self.assertRaises(wire.QlooError):
            sources.FakeSource().fetch(qloo_calls.unsupported_type_request(), tally)
        self.assertEqual(len(tally.rows), 1)

    def test_its_report_says_nothing_live_happened(self):
        self.assertEqual(
            sources.FakeSource().report(), {"source": "fake", "liveCallsToday": 0, "cacheHits": 0}
        )


class LiveRefusesUntilVerified(unittest.TestCase):
    def test_nothing_is_sent_while_anything_is_unverified(self):
        source, transport, _ = live()
        tally = Tally()
        self.assertTrue(measured.UNVERIFIED)
        with self.assertRaises(Refusal) as caught:
            source.fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(caught.exception.code, "shapes_unverified")
        self.assertIn("RESPONSE_SHAPES", caught.exception.detail)
        self.assertEqual((transport.seen, tally.admitted, tally.rows), ([], [], []))
        self.assertEqual(source.report()["liveCallsToday"], 0)

    def test_even_an_answer_in_the_cache_waits_for_verification(self):
        source, transport, _ = live()
        request = qloo_calls.search_request("Dune")
        with verified():
            source.fetch(request)
        with self.assertRaises(Refusal) as caught:
            source.fetch(request)
        self.assertEqual(caught.exception.code, "shapes_unverified")
        self.assertEqual(len(transport.seen), 1)

    def test_once_nothing_is_unverified_it_asks(self):
        source, transport, _ = live()
        with verified():
            reply = source.fetch(qloo_calls.search_request("Dune"))
        self.assertEqual(reply.status, 200)
        self.assertEqual(len(transport.seen), 1)


class Caching(unittest.TestCase):
    def test_the_same_request_is_answered_once_and_logged_as_a_cache_hit(self):
        source, transport, _ = live()
        tally = Tally()
        request = qloo_calls.search_request("Dune")
        with verified():
            first = source.fetch(request, tally)
            second = source.fetch(request, tally)
        self.assertEqual(first.body, second.body)
        self.assertEqual(len(transport.seen), 1)
        self.assertEqual([r[1:] for r in tally.rows][1:], [("cache", 0, False)])
        self.assertEqual((tally.rows[0][1], tally.rows[0][3]), ("miss", True))
        self.assertEqual(tally.admitted, [True])
        self.assertEqual(source.report()["cacheHits"], 1)
        self.assertEqual(source.report()["liveCallsToday"], 1)

    def test_a_different_request_is_a_different_entry(self):
        source, transport, _ = live()
        with verified():
            source.fetch(qloo_calls.search_request("Dune"))
            source.fetch(qloo_calls.search_request("Heat"))
            source.fetch(qloo_calls.search_request("Dune", take=2))
        self.assertEqual(len(transport.seen), 3)

    def test_an_entry_expires_after_the_time_to_live(self):
        source, transport, clock = live(ttl=60)
        request = qloo_calls.search_request("Dune")
        with verified():
            source.fetch(request)
            clock.now += 59
            source.fetch(request)
            self.assertEqual(len(transport.seen), 1)
            clock.now += 2
            source.fetch(request)
        self.assertEqual(len(transport.seen), 2)

    def test_the_cache_is_bounded(self):
        source, transport, _ = live()
        with verified(), mock.patch.object(sources, "CACHE_ENTRIES", 2):
            for name in ("a", "b", "c"):
                source.fetch(qloo_calls.search_request(name))
            source.fetch(qloo_calls.search_request("c"))
            source.fetch(qloo_calls.search_request("a"))
        self.assertEqual(len(transport.seen), 4)
        self.assertEqual(source.report()["cacheEntries"], 2)

    def test_the_cache_key_carries_no_key_and_no_name(self):
        key = fake_key()
        source, _, _ = live(key=key)
        request = qloo_calls.search_request("Dune")
        with verified():
            source.fetch(request)
        for stored in source._cache:
            self.assertNotIn(key, stored)
            self.assertNotIn("Dune", stored)
            self.assertRegex(stored, r"^[0-9a-f]{64}$")
        self.assertEqual(sources.LiveSource.cache_key(request), next(iter(source._cache)))

    def test_a_failed_answer_is_not_cached(self):
        source, transport, _ = live(Transport(failures=[400]))
        request = qloo_calls.search_request("Dune")
        with verified():
            with self.assertRaises(wire.QlooError):
                source.fetch(request)
            source.fetch(request)
        self.assertEqual(len(transport.seen), 2)

    def test_a_hit_costs_nothing_even_when_the_ceiling_is_spent(self):
        source, transport, _ = live(ceiling=1)
        request = qloo_calls.search_request("Dune")
        with verified():
            source.fetch(request)
            source.fetch(request)
            with self.assertRaises(Refusal) as caught:
                source.fetch(qloo_calls.search_request("Heat"))
        self.assertEqual(caught.exception.code, "daily_ceiling_spent")
        self.assertEqual(len(transport.seen), 1)


class BoundedRetry(unittest.TestCase):
    def test_a_429_is_asked_again_after_one_second_and_each_attempt_is_counted(self):
        source, transport, clock = live(Transport(failures=[429]))
        tally = Tally()
        with verified():
            reply = source.fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(reply.status, 200)
        self.assertEqual(clock.slept, [1.0])
        self.assertEqual(len(transport.seen), 2)
        self.assertEqual([r[1] for r in tally.rows], ["miss", "miss"])
        self.assertEqual(tally.admitted, [True, True])
        self.assertEqual(source.report()["liveCallsToday"], 2)

    def test_a_persistent_5xx_is_tried_three_times_after_one_and_three_seconds(self):
        source, transport, clock = live(Transport(failures=[503, 500, 502]))
        tally = Tally()
        with verified(), self.assertRaises(wire.QlooError) as caught:
            source.fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual((caught.exception.code, caught.exception.status), ("qloo_unavailable", 502))
        self.assertEqual(clock.slept, [1.0, 3.0])
        self.assertEqual(len(transport.seen), 3)
        self.assertEqual(len(tally.rows), 3)
        self.assertEqual(source.report()["liveCallsToday"], 3)

    def test_a_persistent_429_ends_as_rate_limited(self):
        source, _, _ = live(Transport(failures=[429, 429, 429]))
        with verified(), self.assertRaises(wire.QlooError) as caught:
            source.fetch(qloo_calls.search_request("Dune"))
        self.assertEqual(caught.exception.code, "qloo_rate_limited")

    def test_nothing_else_is_asked_again(self):
        for status in (400, 401, 403, 404, 302):
            with self.subTest(status):
                source, transport, clock = live(Transport(failures=[status, status]))
                with verified(), self.assertRaises(wire.QlooError):
                    source.fetch(qloo_calls.search_request("Dune"))
                self.assertEqual((len(transport.seen), clock.slept), (1, []))

    def test_a_lost_connection_is_not_asked_again(self):
        class Lost(Transport):
            def __call__(self, request, key, base_url=wire.BASE_URL):
                self.seen.append(request)
                raise wire.QlooError("qloo_unavailable", 0, {})

        source, transport, clock = live(Lost())
        with verified(), self.assertRaises(wire.QlooError):
            source.fetch(qloo_calls.search_request("Dune"))
        self.assertEqual((len(transport.seen), clock.slept), (1, []))

    def test_an_unreadable_answer_is_a_counted_call_and_not_asked_again(self):
        class Garbled(Transport):
            def __call__(self, request, key, base_url=wire.BASE_URL):
                self.seen.append(request)
                raise Refusal(records.UNEXPECTED_SHAPE, "$")

        source, transport, _ = live(Garbled())
        tally = Tally()
        with verified(), self.assertRaises(Refusal) as caught:
            source.fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(caught.exception.code, "qloo_unexpected_shape")
        self.assertEqual((len(transport.seen), len(tally.rows)), (1, 1))

    def test_the_meter_can_stop_a_retry(self):
        source, transport, _ = live(Transport(failures=[429, 429]))
        tally = Tally(limit=1)
        with verified(), self.assertRaises(Refusal) as caught:
            source.fetch(qloo_calls.search_request("Dune"), tally)
        self.assertEqual(caught.exception.code, "over_limit")
        self.assertEqual(len(transport.seen), 1)


class TheDailyCeiling(unittest.TestCase):
    def test_requests_past_the_ceiling_are_refused_and_never_sent(self):
        source, transport, _ = live(ceiling=2)
        with verified():
            source.fetch(qloo_calls.search_request("a"))
            source.fetch(qloo_calls.search_request("b"))
            with self.assertRaises(Refusal) as caught:
                source.fetch(qloo_calls.search_request("c"))
        self.assertEqual((caught.exception.code, caught.exception.detail), ("daily_ceiling_spent", "2 of 2"))
        self.assertEqual(len(transport.seen), 2)
        self.assertEqual(source.report()["liveCallsToday"], 2)

    def test_retries_count_against_it(self):
        source, transport, _ = live(Transport(failures=[503, 503]), ceiling=2)
        with verified(), self.assertRaises(Refusal) as caught:
            source.fetch(qloo_calls.search_request("a"))
        self.assertEqual(caught.exception.code, "daily_ceiling_spent")
        self.assertEqual(len(transport.seen), 2)

    def test_the_count_starts_again_on_the_next_utc_day(self):
        source, _, clock = live(ceiling=1, ttl=10)
        with verified():
            source.fetch(qloo_calls.search_request("a"))
            clock.now += 86400
            source.fetch(qloo_calls.search_request("b"))
        self.assertEqual(source.report()["liveCallsToday"], 1)

    def test_the_meter_is_asked_before_the_ceiling(self):
        source, transport, _ = live(ceiling=0)
        with verified(), self.assertRaises(Refusal) as caught:
            source.fetch(qloo_calls.search_request("a"), Tally(limit=0))
        self.assertEqual(caught.exception.code, "over_limit")
        self.assertEqual(transport.seen, [])


class ChoosingASource(unittest.TestCase):
    def test_the_fake_provider_makes_the_fake(self):
        self.assertIsInstance(sources.make(settings.Settings(provider="fake")), sources.FakeSource)

    def test_live_without_a_key_is_refused_and_never_becomes_the_fake(self):
        transport = Transport()
        with self.assertRaises(Refusal) as caught:
            sources.make(settings.Settings(provider="live"), send=transport)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("no_key", "key: missing"))
        self.assertEqual(transport.seen, [])

    def test_live_with_a_key_takes_its_limits_from_the_settings(self):
        key = fake_key()
        config = settings.Settings(api_key=key, provider="live", daily_live_calls=7, cache_ttl_s=9)
        source = sources.make(config)
        self.assertIsInstance(source, sources.LiveSource)
        self.assertEqual(source.report()["dailyCeiling"], 7)
        self.assertNotIn(key, repr(source))
        self.assertNotIn(key, str(source.report()))

    def test_the_live_source_knows_it_is_live_and_the_fake_does_not(self):
        self.assertEqual((sources.LiveSource.live, sources.FakeSource.live), (True, False))
        self.assertEqual((sources.LiveSource.name, sources.FakeSource.name), ("live", "fake"))


class OverARealSocket(unittest.TestCase):
    def test_the_key_goes_in_the_header_only_and_a_repeat_comes_from_the_cache(self):
        key = fake_key()
        with Stub(sources.FakeSource(), key) as stub, verified():
            source = sources.LiveSource(
                key, daily_ceiling=10, cache_ttl_s=60, base_url=stub.url
            )
            request = qloo_calls.search_request("Khruangbin")
            source.fetch(request)
            source.fetch(request)
        (seen,) = stub.requests
        self.assertEqual(seen["headers"]["X-Api-Key"], key)
        self.assertNotIn(key, seen["path"])
        self.assertEqual(source.report()["cacheHits"], 1)

    def test_a_wrong_key_is_an_auth_refusal_and_not_asked_again(self):
        with Stub(sources.FakeSource(), fake_key()) as stub, verified():
            source = sources.LiveSource(
                fake_key(), daily_ceiling=10, cache_ttl_s=60, base_url=stub.url
            )
            with self.assertRaises(wire.QlooError) as caught:
                source.fetch(qloo_calls.search_request("Dune"))
        self.assertEqual((caught.exception.code, caught.exception.status), ("qloo_auth", 401))
        self.assertEqual(len(stub.requests), 1)

    def test_a_busy_server_is_asked_three_times_with_the_waits_stubbed(self):
        key = fake_key()
        slept = []
        with Stub(Canned(503, {"error": "busy"}), key) as stub, verified():
            source = sources.LiveSource(
                key, daily_ceiling=10, cache_ttl_s=60, base_url=stub.url, sleep=slept.append
            )
            with self.assertRaises(wire.QlooError) as caught:
                source.fetch(qloo_calls.search_request("Dune"))
        self.assertEqual(caught.exception.code, "qloo_unavailable")
        self.assertEqual((len(stub.requests), slept), (3, [1.0, 3.0]))


if __name__ == "__main__":
    unittest.main()
