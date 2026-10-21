import os
import re
import unittest
from unittest import mock

from common_ground import measured, records
from common_ground.refusal import Refusal
from tests.support import RESERVED, fixture, ids

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "common_ground")


def refusal_code(call, *args):
    try:
        call(*args)
    except Refusal as error:
        return error.code, error.detail
    raise AssertionError("no refusal")


class Search(unittest.TestCase):
    def test_reads_candidates_and_drops_a_person(self):
        found = records.read_search(fixture("search.json"))
        names = [c.name for c in found.candidates]
        self.assertEqual(names, ["Sample Supper Room", "Sample Band", "Sample Film", "Sample Show"])
        self.assertEqual(found.dropped_people, 1)
        first, _, film, show = found.candidates
        self.assertEqual(
            (first.type, first.popularity, first.disambiguation),
            ("urn:entity:place", 0.62, "invented restaurant"),
        )
        self.assertEqual((film.popularity, film.disambiguation), (None, None))
        self.assertEqual(show.popularity, 0.1)

    def test_nothing_found_is_no_results(self):
        code, _ = refusal_code(records.read_search, fixture("search_empty.json"))
        self.assertEqual(code, "qloo_no_results")

    def test_only_people_is_no_results_and_says_so(self):
        code, detail = refusal_code(records.read_search, fixture("search_only_people.json"))
        self.assertEqual(code, "qloo_no_results")
        self.assertIn("person", detail)

    def test_unknown_shapes_fail_loudly_naming_the_path(self):
        cases = [
            ([], "$"),
            ({"results": {"entities": []}}, "$.results"),
            ({"results": ["x"]}, "$.results[0]"),
            ({"results": [{"entity_id": "a", "type": "urn:entity:movie"}]}, "$.results[0].name"),
            ({"results": [{"entity_id": "", "name": "n", "type": "t"}]}, "$.results[0].entity_id"),
            ({"results": [{"entity_id": "a", "name": "n"}]}, "$.results[0].type"),
            ({"results": [{"entity_id": "a", "name": "n", "type": "t", "popularity": "hi"}]},
             "$.results[0].popularity"),
            ({"results": [{"entity_id": "a", "name": "n", "type": "t", "disambiguation": 3}]},
             "$.results[0].disambiguation"),
        ]
        for body, path in cases:
            with self.subTest(path=path):
                self.assertEqual(refusal_code(records.read_search, body), ("qloo_unexpected_shape", path))


class Tags(unittest.TestCase):
    def test_reads_tags(self):
        tags = records.read_tags(fixture("tags.json"))
        self.assertEqual([t.name for t in tags], ["Restaurant", "Bar", "Italian"])
        self.assertEqual(tags[0].id, "urn:tag:synthetic:restaurant")

    def test_empty_and_odd(self):
        self.assertEqual(refusal_code(records.read_tags, fixture("tags_empty.json"))[0], "qloo_no_results")
        self.assertEqual(
            refusal_code(records.read_tags, {"results": []}), ("qloo_unexpected_shape", "$.results")
        )
        self.assertEqual(
            refusal_code(records.read_tags, {"results": {"tags": [{"name": "x"}]}}),
            ("qloo_unexpected_shape", "$.results.tags[0].id"),
        )


class GroupSearch(unittest.TestCase):
    def test_reads_places_in_order(self):
        found = records.read_group_search(fixture("group_search.json"))
        self.assertEqual(len(found.places), 6)
        first = found.places[0]
        self.assertEqual((first.name, first.position, first.type), ("Alder Table", 1, "urn:entity:place"))
        self.assertEqual([t.name for t in first.tags], ["Restaurant", "Thai"])
        self.assertEqual(first.address, "10 Fern St, Sample City")
        self.assertEqual(first.website, "https://example.invalid/0")
        self.assertIsNone(found.places[1].website)
        self.assertEqual([p.position for p in found.places], [1, 2, 3, 4, 5, 6])

    def test_aggregate_explainability_is_the_lean_source(self):
        found = records.read_group_search(fixture("group_search.json"))
        self.assertEqual(sorted(found.influence.values()), [0.2, 0.3, 0.5])

    def test_explainability_absent(self):
        found = records.read_group_search(fixture("group_search_plain.json"))
        self.assertIsNone(found.influence)
        self.assertEqual(found.places[0].tags, ())
        self.assertIsNone(found.places[0].address)

    def test_a_200_with_no_entities_is_no_results(self):
        code, _ = refusal_code(records.read_group_search, fixture("empty_entities.json"))
        self.assertEqual(code, "qloo_no_results")

    def test_unknown_shapes(self):
        good = fixture("group_search_plain.json")
        cases = {
            "$.results.entities[0].name": lambda b: b["results"]["entities"][0].pop("name"),
            "$.results.entities[0].tags": lambda b: b["results"]["entities"][0].update(tags="restaurant"),
            "$.results.entities[0].properties": lambda b: b["results"]["entities"][0].update(properties=[]),
            "$.results.entities[0].properties.address":
                lambda b: b["results"]["entities"][0].update(properties={"address": 5}),
        }
        for path, damage in cases.items():
            body = {**good, "results": {"entities": [dict(e) for e in good["results"]["entities"]]}}
            damage(body)
            with self.subTest(path=path):
                self.assertEqual(
                    refusal_code(records.read_group_search, body), ("qloo_unexpected_shape", path)
                )

    def test_a_score_outside_zero_to_one_is_refused(self):
        body = fixture("group_search.json")
        body["query"]["explainability"]["signal.interests.entities"][0]["score"] = 1.5
        self.assertEqual(refusal_code(records.read_group_search, body)[0], "qloo_unexpected_shape")

    def test_aggregate_explainability_of_another_form_is_refused(self):
        body = fixture("group_search_plain.json")
        body["query"] = {"explainability": {"something_else": []}}
        self.assertEqual(
            refusal_code(records.read_group_search, body),
            ("qloo_unexpected_shape", "$.query.explainability.signal.interests.entities"),
        )
        body["query"] = {"explainability": {}}
        self.assertIsNone(records.read_group_search(body).influence)


class Ranking(unittest.TestCase):
    def asked(self):
        return [e["entity_id"] for e in fixture("group_search.json")["results"]["entities"]]

    def test_rank_is_response_order(self):
        asked = self.asked()
        ranking = records.read_ranking(fixture("ranking_b.json"), asked)
        self.assertEqual([r.entity_id for r in ranking.ranked], list(reversed(asked)))
        self.assertEqual([r.rank for r in ranking.ranked], [1, 2, 3, 4, 5, 6])
        self.assertEqual(ranking.ranked[0].affinity, 0.95)
        self.assertEqual((ranking.requested, ranking.unrequested, ranking.returned_share), (6, 0, 1.0))
        self.assertTrue(ranking.non_increasing)

    def test_because_pairs(self):
        ranking = records.read_ranking(fixture("ranking_a.json"), self.asked())
        self.assertEqual(len(ranking.ranked[0].because), 2)
        self.assertEqual(ranking.ranked[0].because[0][1], 0.6)

    def test_ids_not_asked_for_are_counted_and_set_aside(self):
        asked = self.asked()[:4]
        ranking = records.read_ranking(fixture("ranking_a.json"), asked)
        self.assertEqual([r.rank for r in ranking.ranked], [1, 2, 3, 4])
        self.assertEqual((ranking.requested, ranking.unrequested), (4, 2))

    def test_a_short_answer_has_a_share_below_one(self):
        asked = self.asked() + ids(4, start=900)
        ranking = records.read_ranking(fixture("ranking_a.json"), asked)
        self.assertEqual(len(ranking.ranked), 6)
        self.assertAlmostEqual(ranking.returned_share, 0.6)

    def test_duplicates_count_once(self):
        body = fixture("ranking_a.json")
        body["results"]["entities"].append(dict(body["results"]["entities"][0]))
        self.assertEqual(len(records.read_ranking(body, self.asked()).ranked), 6)

    def test_order_that_rises_is_flagged(self):
        body = fixture("ranking_a.json")
        body["results"]["entities"][2]["query"]["affinity"] = 0.99
        self.assertFalse(records.read_ranking(body, self.asked()).non_increasing)

    def test_no_affinity_is_not_an_error(self):
        ranking = records.read_ranking(fixture("ranking_no_affinity.json"), self.asked())
        self.assertTrue(all(r.affinity is None for r in ranking.ranked))
        self.assertTrue(ranking.non_increasing)

    def test_affinity_outside_zero_to_one_is_refused(self):
        body = fixture("ranking_a.json")
        body["results"]["entities"][0]["query"]["affinity"] = 7
        self.assertEqual(refusal_code(records.read_ranking, body, self.asked())[0], "qloo_unexpected_shape")

    def test_empty(self):
        code, _ = refusal_code(records.read_ranking, fixture("empty_entities.json"), [])
        self.assertEqual(code, "qloo_no_results")

    def test_explainability_of_another_form_is_refused(self):
        body = fixture("ranking_a.json")
        body["results"]["entities"][0]["query"]["explainability"] = {"something_else": []}
        code, detail = refusal_code(records.read_ranking, body, self.asked())
        self.assertEqual(code, "qloo_unexpected_shape")
        self.assertTrue(detail.startswith("$.results.entities[0].query.explainability"))

    def test_a_missing_affinity_path_means_no_affinity(self):
        with mock.patch.object(measured, "AFFINITY_PATH", None):
            ranking = records.read_ranking(fixture("ranking_a.json"), self.asked())
        self.assertTrue(all(r.affinity is None for r in ranking.ranked))

    def test_explainability_path_can_be_unset(self):
        with mock.patch.object(measured, "EXPLAIN_PATH", None):
            ranking = records.read_ranking(fixture("ranking_a.json"), self.asked())
        self.assertTrue(all(r.because == () for r in ranking.ranked))


class Skeleton(unittest.TestCase):
    def test_paths_types_and_counts_without_values(self):
        skel = records.skeleton(fixture("group_search.json"))
        self.assertEqual(skel["$.results.entities[].query.affinity"], ("number", 6))
        self.assertEqual(skel["$.results.entities[].properties.website"], ("string", 3))
        self.assertEqual(skel["$.query.locality.signal"], ("number", 1))
        self.assertEqual(skel["$.results.entities[]"], ("object", 6))
        blob = " ".join(skel)
        self.assertNotIn("Alder", blob)
        self.assertFalse(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", blob))

    def test_keys_that_look_like_ids_are_not_printed(self):
        body = {"by_id": {RESERVED + "000000000001": 1, "a" * 28: 2, "urn:x:y": 3}}
        skel = records.skeleton(body)
        self.assertEqual(sorted(skel), ["$", "$.by_id", "$.by_id.<key>"])
        self.assertEqual(skel["$.by_id.<key>"], ("number", 3))

    def test_mixed_types_are_listed(self):
        mixed = records.skeleton({"a": [1, "x", None, True]})
        self.assertEqual(mixed["$.a[]"], ("boolean|null|number|string", 4))


class OnlyRecordsReadsAResponse(unittest.TestCase):
    def test_no_other_module_subscripts_a_response_key(self):
        pattern = re.compile(
            r"""(\[|\.get\()\s*["']"""
            r"""(results|entities|entity_id|affinity|explainability|properties|disambiguation|popularity)"""
            r"""["']"""
        )
        exempt = {"records.py", "sources.py"}
        for name in sorted(os.listdir(PACKAGE)):
            if name.endswith(".py") and name not in exempt:
                with open(os.path.join(PACKAGE, name), encoding="utf-8") as fh:
                    for number, line in enumerate(fh, 1):
                        with self.subTest(module=name, line=number):
                            self.assertIsNone(pattern.search(line), line)


if __name__ == "__main__":
    unittest.main()
