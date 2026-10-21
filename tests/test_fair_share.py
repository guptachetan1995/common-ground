import inspect
import unittest

from common_ground import fair_share, records
from tests.support import ids


def ranking(order, affinities=None, size=None):
    """A member's ranking: `order` lists entity ids best first; affinities, if given, run alongside."""
    ranked = tuple(
        records.Ranked(entity, i + 1, None if affinities is None else affinities[i], ())
        for i, entity in enumerate(order)
    )
    return records.Ranking(ranked, size or len(order), 0, True)


def spaced(count, top=0.95, step=0.05):
    """Affinities far enough apart that no tie tolerance applies."""
    return [round(top - step * i, 3) for i in range(count)]


def by_rank(long_list, ranks):
    """A full ranking of long_list: the given ids take the given ranks, the rest follow in list order."""
    slots = [None] * len(long_list)
    for entity, rank in ranks.items():
        slots[rank - 1] = entity
    rest = iter(e for e in long_list if e not in ranks)
    return [slot if slot is not None else next(rest) for slot in slots]


class Pieces(unittest.TestCase):
    def test_half_is_the_ceiling(self):
        self.assertEqual([fair_share.half(m) for m in (50, 25, 10, 11, 1)], [25, 13, 5, 6, 1])

    def test_bar_length_is_position_in_the_ranking(self):
        self.assertEqual(fair_share.bar_length(1, 50), 1.0)
        self.assertEqual(fair_share.bar_length(50, 50), 0.02)
        self.assertAlmostEqual(fair_share.bar_length(26, 50), 0.5)
        self.assertEqual(fair_share.bar_length(None, 50), 0.0)

    def test_bands_are_qloos_and_say_nothing_in_the_gap(self):
        table = {0.95: "Very High", 0.81: "Very High", 0.8: "High", 0.7: "High", 0.6: "High", 0.55: None,
                 0.51: None, 0.5: "Medium", 0.49: "Low", 0.0: "Low", None: None}
        for affinity, name in table.items():
            with self.subTest(affinity=affinity):
                self.assertEqual(fair_share.band(affinity), name)

    def test_the_constants_are_the_planned_ones(self):
        self.assertEqual(
            (fair_share.TIE_EPSILON, fair_share.TIE_RANKS, fair_share.MIN_LONG_LIST, fair_share.PICKS_SHOWN,
             fair_share.NEAR_SHOWN, fair_share.EXPLAIN_MIN, fair_share.MAX_MEMBERS, fair_share.MAX_FAVOURITES,
             fair_share.CALL_LIMIT_DEFAULT, fair_share.CALL_LIMIT_MAX),
            (0.02, 2, 10, 5, 3, 0.1, 6, 3, 30, 60),
        )

    def test_no_composite_score_exists(self):
        names = [n for n, _ in inspect.getmembers(fair_share)]
        words = ("average", "mean", "composite", "total_score")
        self.assertFalse([n for n in names if any(w in n.lower() for w in words)])
        self.assertFalse([f for f in fair_share.Standing.__dataclass_fields__ if "score" in f])


class UpperHalf(unittest.TestCase):
    long_list = ids(10)

    def inside(self, affinities, order=None):
        order = order or self.long_list
        return fair_share.upper_half_ids(ranking(order, affinities), 10)

    def test_without_affinity_ranks_up_to_half_plus_two_count(self):
        inside = self.inside(None)
        self.assertEqual(inside, set(self.long_list[:7]))
        self.assertNotIn(self.long_list[7], inside)

    def test_with_affinity_the_line_is_the_affinity_of_the_half_way_place(self):
        # rank 5 is the line at 0.75; the tolerance reaches down to 0.73
        affinities = [0.95, 0.9, 0.85, 0.8, 0.75, 0.74, 0.73, 0.7, 0.6, 0.5]
        self.assertEqual(self.inside(affinities), set(self.long_list[:7]))

    def test_the_tolerance_is_inclusive_and_stops_at_the_next_gap(self):
        affinities = [0.95, 0.9, 0.85, 0.8, 0.75, 0.731, 0.729, 0.7, 0.6, 0.5]
        self.assertEqual(self.inside(affinities), set(self.long_list[:6]))

    def test_the_tolerance_survives_binary_rounding(self):
        affinities = [0.95, 0.93, 0.92, 0.91, 0.91, 0.89, 0.88, 0.5, 0.4, 0.3]
        inside = self.inside(affinities)
        self.assertIn(self.long_list[5], inside)
        self.assertNotIn(self.long_list[6], inside)

    def test_a_tie_can_run_past_two_ranks(self):
        self.assertEqual(self.inside([0.8] * 10), set(self.long_list))

    def test_with_affinity_known_the_two_rank_tolerance_does_not_apply(self):
        affinities = [0.95, 0.9, 0.85, 0.8, 0.7, 0.3, 0.29, 0.2, 0.1, 0.0]
        self.assertEqual(self.inside(affinities), set(self.long_list[:5]))

    def test_no_affinity_at_the_line_falls_back_to_ranks(self):
        affinities = [0.95, 0.9, 0.85, 0.8, None, 0.79, 0.78, 0.2, 0.1, 0.0]
        self.assertEqual(self.inside(affinities), set(self.long_list[:7]))

    def test_a_place_the_ranking_leaves_out_is_outside(self):
        short = ranking(self.long_list[:6], spaced(6))
        inside = fair_share.upper_half_ids(short, 10)
        self.assertEqual(inside, set(self.long_list[:5]))
        self.assertNotIn(self.long_list[9], inside)

    def test_odd_sizes_round_the_half_up(self):
        order = ids(11)
        inside = fair_share.upper_half_ids(ranking(order, spaced(11, step=0.07)), 11)
        self.assertEqual(inside, set(order[:6]))


class Evaluate(unittest.TestCase):
    long_list = ids(10)
    a, b, c = "A", "B", "C"

    def members(self, *rankings):
        names = [self.a, self.b, self.c][: len(rankings)]
        return dict(zip(names, rankings)), names

    def evaluate(self, *rankings):
        given, names = self.members(*rankings)
        return fair_share.evaluate(self.long_list, given, names)

    def spaced(self, order):
        return ranking(order, spaced(len(order)))

    def test_common_is_exactly_the_upper_half_of_everyone_and_one_rank_outside_is_near(self):
        ll = self.long_list
        first = self.spaced(ll)
        second = self.spaced([ll[3], ll[2], ll[1], ll[0], ll[9], ll[4], ll[8], ll[7], ll[6], ll[5]])
        result = self.evaluate(first, second)
        self.assertEqual({s.entity_id for s in result.with_status("common")}, set(ll[:4]))
        by_id = {s.entity_id: s for s in result.standings}
        self.assertEqual((by_id[ll[4]].status, by_id[ll[4]].left_out), ("near", (self.b,)))
        self.assertEqual((by_id[ll[9]].status, by_id[ll[9]].left_out), ("near", (self.a,)))
        self.assertEqual((by_id[ll[5]].status, by_id[ll[5]].left_out), ("set_aside", (self.a, self.b)))
        self.assertEqual([s.entity_id for s in result.with_status("near")], [ll[4], ll[9]])
        self.assertEqual(result.found_common, 4)
        self.assertFalse(result.no_place_comes_close)

    def test_common_places_are_ordered_by_worst_rank_then_sum_then_position(self):
        ll = self.long_list
        p, q, r, s, x = ll[:5]
        first = by_rank(ll, {p: 1, r: 2, s: 3, q: 4, x: 5})
        second = by_rank(ll, {s: 1, q: 2, x: 3, r: 4, p: 5})
        result = self.evaluate(self.spaced(first), self.spaced(second))
        common = result.with_status("common")
        self.assertEqual([c.entity_id for c in common], [s, q, r, p, x])
        self.assertEqual(
            [c.placed_by for c in common],
            ["worst_rank", "group_position", "worst_rank", "sum_of_ranks", "sum_of_ranks"],
        )

    def test_a_single_common_place_is_placed_by_its_worst_rank(self):
        ll = self.long_list
        first = by_rank(ll, {ll[7]: 1, ll[0]: 2, ll[1]: 3, ll[2]: 4, ll[3]: 5})
        second = by_rank(ll, {ll[7]: 5, ll[8]: 1, ll[9]: 2, ll[6]: 3, ll[5]: 4})
        result = self.evaluate(self.spaced(first), self.spaced(second))
        only = [(c.entity_id, c.placed_by) for c in result.with_status("common")]
        self.assertEqual(only, [(ll[7], "worst_rank")])

    def test_identical_rankings_share_the_upper_half(self):
        result = self.evaluate(self.spaced(self.long_list), self.spaced(self.long_list))
        self.assertEqual([s.entity_id for s in result.with_status("common")], self.long_list[:5])
        self.assertEqual(result.found_common, 5)

    def test_disjoint_rankings_leave_no_common_place(self):
        forward = self.spaced(self.long_list)
        backward = self.spaced(list(reversed(self.long_list)))
        result = self.evaluate(forward, backward)
        self.assertEqual(result.found_common, 0)
        near = result.with_status("near")
        self.assertEqual(len(near), fair_share.NEAR_SHOWN)
        self.assertTrue(all(len(s.left_out) == 1 for s in near))
        self.assertFalse(result.no_place_comes_close)

    def test_near_places_are_ordered_by_fewest_left_out_then_the_worst_rank_among_them_then_position(self):
        ll = self.long_list
        near = self.evaluate(self.spaced(ll), self.spaced(list(reversed(ll)))).with_status("near")
        self.assertEqual([s.entity_id for s in near], [ll[4], ll[5], ll[3]])
        self.assertEqual([max(m.rank for m in s.members if not m.in_upper_half) for s in near], [6, 6, 7])

    def test_near_allows_at_most_half_of_those_ranked_to_be_left_out(self):
        ll = self.long_list
        for k in (2, 3, 4, 5, 6):
            rankings = {f"m{i}": self.spaced(ll if i % 2 == 0 else list(reversed(ll))) for i in range(k)}
            result = fair_share.evaluate(ll, rankings, list(rankings))
            allowed = max(1, k // 2)
            near = result.with_status("near")
            for standing in near:
                with self.subTest(members=k):
                    self.assertLessEqual(len(standing.left_out), allowed)
            for standing in result.with_status("set_aside"):
                with self.subTest(members=k, place=standing.entity_id):
                    self.assertTrue(len(standing.left_out) > allowed or len(near) == fair_share.NEAR_SHOWN)

    def test_with_one_member_ranked_a_place_outside_their_half_is_near(self):
        result = fair_share.evaluate(self.long_list, {self.a: self.spaced(self.long_list)}, [self.a, self.b])
        self.assertEqual(result.found_common, 5)
        self.assertEqual(len(result.with_status("near")), fair_share.NEAR_SHOWN)
        self.assertEqual(result.unranked_members, (self.b,))
        self.assertEqual(result.ranked_members, (self.a,))

    def test_an_early_stop_reports_who_was_not_ranked(self):
        forward = self.spaced(self.long_list)
        backward = self.spaced(list(reversed(self.long_list)))
        given = {self.a: forward, self.b: backward}
        result = fair_share.evaluate(self.long_list, given, [self.a, self.b, self.c])
        self.assertEqual(result.found_common, 0)
        self.assertEqual(result.unranked_members, (self.c,))
        self.assertTrue(all(len(s.members) == 2 for s in result.standings))

    def test_no_place_comes_close_needs_a_ranking_that_leaves_places_out(self):
        # With full rankings this cannot happen: three halves of twelve places hold eighteen slots, so some
        # place sits in two of them. It happens when rankings cover few places, which count as outside.
        ll = ids(12)
        short = {
            "A": ranking(ll[0:4], [0.9, 0.8, 0.7, 0.6], size=12),
            "B": ranking(ll[4:8], [0.9, 0.8, 0.7, 0.6], size=12),
            "C": ranking(ll[8:12], [0.9, 0.8, 0.7, 0.6], size=12),
        }
        result = fair_share.evaluate(ll, short, ["A", "B", "C"])
        self.assertEqual(result.found_common, 0)
        self.assertEqual(result.with_status("near"), ())
        self.assertTrue(result.no_place_comes_close)
        self.assertEqual({len(s.left_out) for s in result.standings}, {2})
        self.assertTrue(all(s.status == "set_aside" for s in result.standings))

    def test_a_partial_ranking_counts_the_missing_place_as_outside_with_no_figure(self):
        ll = self.long_list
        partial = ranking(ll[:8], spaced(8))
        result = fair_share.evaluate(ll, {self.a: self.spaced(ll), self.b: partial}, [self.a, self.b])
        gone = next(s for s in result.standings if s.entity_id == ll[9])
        theirs = next(m for m in gone.members if m.member == self.b)
        self.assertEqual(
            (theirs.rank, theirs.ranked, theirs.in_upper_half, theirs.bar, theirs.affinity, theirs.band),
            (None, False, False, 0.0, None, None),
        )

    def test_each_member_standing_carries_rank_bar_affinity_and_band(self):
        result = self.evaluate(self.spaced(self.long_list), self.spaced(list(reversed(self.long_list))))
        top = next(s for s in result.standings if s.entity_id == self.long_list[0])
        first, second = top.members
        self.assertEqual((first.rank, first.bar, first.affinity, first.band), (1, 1.0, 0.95, "Very High"))
        self.assertEqual((second.rank, second.bar), (10, 0.1))
        self.assertEqual(second.affinity, 0.5)
        self.assertEqual(second.band, "Medium")

    def test_picks_are_capped_but_the_count_is_not(self):
        everyone = self.spaced(self.long_list)
        result = self.evaluate(everyone, everyone)
        self.assertEqual(len(result.picks), 5)
        longer = ids(20)
        wide = fair_share.evaluate(longer, {"A": ranking(longer, spaced(20, step=0.04))}, ["A"])
        self.assertEqual(wide.found_common, 10)
        self.assertEqual(len(wide.picks), fair_share.PICKS_SHOWN)

    def test_every_place_gets_exactly_one_standing(self):
        result = self.evaluate(self.spaced(self.long_list), self.spaced(list(reversed(self.long_list))))
        self.assertEqual(sorted(s.entity_id for s in result.standings), sorted(self.long_list))

    def test_a_tie_at_the_line_keeps_a_place_common(self):
        ll = self.long_list
        tied = [0.95, 0.9, 0.85, 0.8, 0.75, 0.74, 0.5, 0.4, 0.3, 0.2]
        other = self.spaced(by_rank(ll, {ll[5]: 1}))
        with_tie = fair_share.evaluate(ll, {"A": ranking(ll, tied), "B": other}, ["A", "B"])
        self.assertIn(ll[5], [s.entity_id for s in with_tie.with_status("common")])
        without = fair_share.evaluate(ll, {"A": self.spaced(ll), "B": other}, ["A", "B"])
        six = next(s for s in without.standings if s.entity_id == ll[5])
        self.assertEqual((six.status, six.left_out), ("near", ("A",)))


class ChanceOfSharing(unittest.TestCase):
    def test_expected_places_by_group_size_at_fifty(self):
        expected = [fair_share.expected_by_chance(50, n) for n in (2, 3, 4, 5, 6)]
        self.assertEqual(expected, [12.5, 6.3, 3.1, 1.6, 0.8])

    def test_expected_places_for_a_twenty_five_place_list(self):
        expected = [fair_share.expected_by_chance(25, n) for n in (2, 3, 4, 5, 6)]
        self.assertEqual(expected, [6.8, 3.5, 1.8, 1.0, 0.5])

    def test_the_printed_line(self):
        self.assertEqual(
            fair_share.chance_line(50, 4, 7),
            "unrelated rankings would share about 3.1 of 50; this group shares 7",
        )
        self.assertEqual(
            fair_share.chance_line(50, 2, 0),
            "unrelated rankings would share about 12.5 of 50; this group shares 0",
        )

    def test_the_evaluation_prints_it(self):
        ll = ids(50)
        everyone = {m: ranking(ll, spaced(50, step=0.015, top=0.97)) for m in "ABCD"}
        result = fair_share.evaluate(ll, everyone, list("ABCD"))
        self.assertTrue(
            result.chance.startswith("unrelated rankings would share about 3.1 of 50; this group shares ")
        )
        self.assertTrue(result.chance.endswith(str(result.found_common)))

    def test_it_counts_the_members_ranked_so_far(self):
        ll = ids(10)
        one = fair_share.evaluate(ll, {"A": ranking(ll, spaced(10))}, ["A", "B"])
        self.assertIn("about 5.0 of 10", one.chance)


class Lean(unittest.TestCase):
    def test_lean_sums_a_members_favourites_in_qloos_aggregate(self):
        influence = {"e1": 0.3, "e2": 0.2, "e3": 0.1}
        lean = fair_share.lean_by_member(influence, {"m1": ["e1", "e2"], "m2": ["e3"], "m3": ["zz"]})
        self.assertEqual(lean, {"m1": 0.5, "m2": 0.1, "m3": 0.0})

    def test_least_led_on_first_and_listed_order_otherwise(self):
        members = ["m1", "m2", "m3", "m4"]
        lean = {"m1": 0.5, "m2": 0.1, "m3": 0.1, "m4": 0.3}
        self.assertEqual(fair_share.order_by_lean(members, lean), ["m2", "m3", "m4", "m1"])
        self.assertEqual(fair_share.order_by_lean(members, None), members)
        self.assertEqual(fair_share.order_by_lean(members, {}), members)

    def test_because_lines_name_this_members_favourites_at_or_above_the_minimum(self):
        raw = (("e1", 0.42), ("e2", 0.1), ("e3", 0.09), ("other", 0.9))
        lines = fair_share.because_lines(raw, {"e1": "f1", "e2": "f2", "e3": "f3"})
        self.assertEqual(lines, [{"favourite": "f1", "score": 0.42}, {"favourite": "f2", "score": 0.1}])


if __name__ == "__main__":
    unittest.main()
