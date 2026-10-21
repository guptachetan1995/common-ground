import unittest
from unittest import mock

from common_ground import measured, qloo_calls
from common_ground.refusal import Refusal
from tests.support import conditions, ids

FAVOURITES = ids(8)
LONG_LIST = ids(50, start=100)


def group(**changes):
    return qloo_calls.group_search_request(conditions(**changes), FAVOURITES)


def ranking(**changes):
    return qloo_calls.ranking_request(conditions(**changes), FAVOURITES[:2], LONG_LIST)


def every_request():
    return [
        qloo_calls.search_request("Some Band"),
        qloo_calls.tags_request("restaurant"),
        group(),
        group(radiusM=500),
        group(kindTag=None, priceMin=None, priceMax=None),
        ranking(),
        ranking(radiusM=0),
        qloo_calls.unsupported_type_request(),
    ]


class Allowlist(unittest.TestCase):
    def test_every_builder_stays_inside_its_allowlist(self):
        for request in every_request():
            allowed = {
                "/search": qloo_calls.SEARCH_PARAMS,
                "/v2/tags": qloo_calls.TAG_PARAMS,
                "/v2/insights": qloo_calls.PLACE_PARAMS,
            }[request.path]
            with self.subTest(path=request.path, params=request.params):
                self.assertLessEqual({name for name, _ in request.params}, allowed)

    def test_an_unknown_parameter_is_refused_at_build_time(self):
        for request in (group(), ranking()):
            with self.assertRaises(Refusal) as caught:
                qloo_calls.add_param(request, "bias.quality", "5")
            self.assertEqual(
                (caught.exception.code, caught.exception.detail), ("param_refused", "bias.quality")
            )

    def test_demographic_signals_are_refused_and_never_built(self):
        for name in ("signal.demographics.audiences", "signal.demographics.age", "filter.demographics"):
            with self.assertRaises(Refusal) as caught:
                qloo_calls.add_param(group(), name, "x")
            self.assertEqual(caught.exception.code, "param_refused")
        for request in every_request():
            self.assertFalse([n for n, _ in request.params if "demographic" in n])

    def test_a_weight_object_is_refused(self):
        for value in ({"entity": "x", "weight": 2}, [{"entity": "x"}], 1.5, object()):
            with self.assertRaises(Refusal) as caught:
                qloo_calls.add_param(group(), "signal.interests.entities", value)
            self.assertEqual(caught.exception.code, "param_refused")

    def test_only_place_insights_and_known_paths(self):
        for params in (
            [("filter.type", "urn:entity:artist")],
            [("take", 5)],
            [("filter.type", "a"), ("filter.type", "b")],
        ):
            with self.assertRaises(Refusal):
                qloo_calls._checked("/v2/insights", params)
        for path in ("/v2/recommendations", "/recs", "/v2/analysis/compare", "/v2/trending"):
            with self.assertRaises(Refusal):
                qloo_calls._checked(path, [("take", 1)])

    def test_all_requests_are_get_requests_without_a_key(self):
        for request in every_request():
            self.assertFalse(hasattr(request, "method"))
            self.assertNotIn("key", request.query_string().lower())


class GroupSearch(unittest.TestCase):
    def test_parameters_and_order(self):
        request = group()
        self.assertEqual(request.path, "/v2/insights")
        self.assertEqual(request.as_dict(), {
            "filter.type": "urn:entity:place",
            "signal.interests.entities": ",".join(FAVOURITES),
            "filter.exclude.entities": ",".join(FAVOURITES),
            "filter.location.query": "Sample City",
            "filter.hours": "friday",
            "filter.price_level.min": "2",
            "filter.price_level.max": "3",
            "filter.tags": "urn:tag:synthetic:restaurant",
            "feature.explainability": "true",
            "take": "50",
        })
        self.assertEqual(
            [n for n, _ in request.params][:3],
            ["filter.type", "signal.interests.entities", "filter.exclude.entities"],
        )

    def test_a_condition_left_out_is_not_sent(self):
        names = {n for n, _ in group(kindTag=None, priceMin=None, priceMax=None, day=None).params}
        gone = {"filter.tags", "filter.price_level.min", "filter.price_level.max", "filter.hours"}
        self.assertFalse(names & gone)
        self.assertIn("filter.location.query", names)

    def test_radius_goes_with_the_location_query(self):
        self.assertEqual(group(radiusM=0).as_dict()["filter.location.radius"], "0")
        self.assertNotIn("filter.location.radius", group().as_dict())


class Ranking(unittest.TestCase):
    def test_signal_is_the_member_alone_and_every_long_list_id_is_sent(self):
        request = ranking().as_dict()
        self.assertEqual(request["filter.type"], "urn:entity:place")
        self.assertEqual(request["signal.interests.entities"], ",".join(FAVOURITES[:2]))
        self.assertEqual(request["filter.results.entities"].split(","), LONG_LIST)
        self.assertEqual(request["take"], "50")
        self.assertNotIn("filter.exclude.entities", request)

    def test_it_differs_from_the_group_search_in_the_signal_and_the_set_only(self):
        a, b = group().as_dict(), ranking().as_dict()
        differing = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
        self.assertEqual(
            differing,
            {"signal.interests.entities", "filter.exclude.entities", "filter.results.entities"},
        )

    def test_the_conditions_are_the_same_whatever_they_are(self):
        for changes in (
            {}, {"radiusM": 800}, {"day": "sunday"}, {"priceMin": 1, "priceMax": 4}, {"kindTag": None},
            {"placeText": "Elsewhere"},
        ):
            a, b = group(**changes).as_dict(), ranking(**changes).as_dict()
            for name in ("filter.location.query", "filter.location.radius", "filter.hours",
                         "filter.price_level.min", "filter.price_level.max", "filter.tags"):
                with self.subTest(changes=changes, name=name):
                    self.assertEqual(a.get(name), b.get(name))

    def test_a_request_for_fifty_ids_is_a_short_url(self):
        self.assertLess(len(ranking().query_string()), 4000)


class Search(unittest.TestCase):
    def test_types_in_the_comma_form_and_never_a_person(self):
        request = qloo_calls.search_request("Katz's Delicatessen")
        values = request.as_dict()
        self.assertEqual(values["query"], "Katz's Delicatessen")
        self.assertEqual(values["take"], "5")
        self.assertEqual(values["types"].split(","), list(measured.FAVOURITE_TYPES))
        self.assertNotIn("person", values["types"])
        self.assertEqual(len([n for n, _ in request.params if n == "types"]), 1)

    def test_the_repeated_form(self):
        with mock.patch.object(measured, "TYPES_FORM", "repeated"):
            request = qloo_calls.search_request("x")
        self.assertEqual([v for n, v in request.params if n == "types"], list(measured.FAVOURITE_TYPES))

    def test_tags(self):
        self.assertEqual(
            qloo_calls.tags_request("restaurant").as_dict(), {"filter.query": "restaurant", "take": "10"}
        )


class WhatTheProbeFixes(unittest.TestCase):
    def test_a_condition_the_probe_found_ignored_is_dropped(self):
        spelled = {**measured.CONDITIONS_OK, "day": None, "price": None, "kind": None}
        with mock.patch.object(measured, "CONDITIONS_OK", spelled):
            names = {n for n, _ in group().params}
        self.assertFalse(names & {"filter.hours", "filter.price_level.min", "filter.tags"})

    def test_the_location_fallback_spelling(self):
        spelled = {**measured.CONDITIONS_OK, "location": "filter.geocode.name"}
        with mock.patch.object(measured, "CONDITIONS_OK", spelled):
            request = group(radiusM=300)
        self.assertEqual(request.as_dict()["filter.geocode.name"], "Sample City")
        self.assertNotIn("filter.location.radius", request.as_dict())

    def test_explainability_is_not_asked_for_when_the_probe_found_it_absent(self):
        with mock.patch.object(measured, "EXPLAIN_PATH", None):
            with mock.patch.object(measured, "LEAN_PATH", None):
                self.assertNotIn("feature.explainability", group().as_dict())
        self.assertIn("feature.explainability", group().as_dict())

    def test_the_long_list_comes_from_measured(self):
        with mock.patch.object(measured, "LONG_LIST", 25):
            self.assertEqual(group().as_dict()["take"], "25")


class Encoding(unittest.TestCase):
    def test_commas_stay_and_spaces_are_escaped(self):
        request = qloo_calls.group_search_request(conditions(placeText="New York City"), ["a", "b"])
        query = request.query_string()
        self.assertIn("signal.interests.entities=a,b", query)
        self.assertIn("filter.location.query=New%20York%20City", query)

    def test_repeated_names_merge_in_the_dict_view(self):
        request = qloo_calls.Request("/search", (("types", "a"), ("types", "b")))
        self.assertEqual(request.as_dict(), {"types": "a,b"})

    def test_the_unsupported_type_probe_request(self):
        self.assertEqual(
            qloo_calls.unsupported_type_request().params,
            (("filter.type", "urn:entity:destination"), ("take", "1")),
        )


if __name__ == "__main__":
    unittest.main()
