"""The fairness rule: who is inside, who is left out, and how likely that is by chance.

People are compared by position in their own ranking, never by raw affinity, and nothing here
averages, subtracts or sums an affinity. Input rankings are records.Ranking values (each place with a
1-based rank and an optional affinity).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence

TIE_EPSILON = 0.02
TIE_RANKS = 2
MIN_LONG_LIST = 10
MIN_RANKED_SHARE = 0.8
PICKS_SHOWN = 5
NEAR_SHOWN = 3
EXPLAIN_MIN = 0.1
MAX_MEMBERS = 6
MAX_FAVOURITES = 3
CALL_LIMIT_DEFAULT = 30
CALL_LIMIT_MAX = 60

# Affinities arrive as decimals; this keeps 0.91 - 0.02 against 0.89 from flipping on binary rounding.
_SLACK = 1e-9


def half(size: int) -> int:
    return (size + 1) // 2


def bar_length(rank: int | None, size: int) -> float:
    if rank is None:
        return 0.0
    return (size - rank + 1) / size


def band(affinity: float | None) -> str | None:
    """Qloo's named bands. Nothing is said for a value Qloo names no band for."""
    if affinity is None:
        return None
    if affinity > 0.8:
        return "Very High"
    if affinity >= 0.6:
        return "High"
    if affinity == 0.5:
        return "Medium"
    if affinity < 0.5:
        return "Low"
    return None


def _tenths(value: Fraction) -> float:
    return math.floor(value * 10 + Fraction(1, 2)) / 10


def expected_by_chance(size: int, members: int) -> float:
    """Places expected in every upper half if the rankings were unrelated, to one decimal."""
    return _tenths(size * Fraction(half(size), size) ** members)


def chance_line(size: int, members: int, found: int) -> str:
    expected = expected_by_chance(size, members)
    return f"unrelated rankings would share about {expected:.1f} of {size}; this group shares {found}"


class _Table:
    def __init__(self, ranking, size: int) -> None:
        self.by_id = {item.entity_id: item for item in ranking.ranked}
        self.half = half(size)
        at_line = next((item for item in ranking.ranked if item.rank == self.half), None)
        self.line = None if at_line is None else at_line.affinity

    def inside(self, entity_id: str) -> bool:
        item = self.by_id.get(entity_id)
        if item is None:
            return False
        if item.rank <= self.half:
            return True
        if self.line is not None and item.affinity is not None:
            return item.affinity + _SLACK >= self.line - TIE_EPSILON
        return item.rank <= self.half + TIE_RANKS


@dataclass(frozen=True)
class MemberStanding:
    member: str
    rank: int | None
    bar: float
    affinity: float | None
    band: str | None
    in_upper_half: bool
    ranked: bool


@dataclass(frozen=True)
class Standing:
    entity_id: str
    position: int
    status: str
    members: tuple[MemberStanding, ...]
    left_out: tuple[str, ...]
    placed_by: str | None


@dataclass(frozen=True)
class Evaluation:
    size: int
    half: int
    ranked_members: tuple[str, ...]
    unranked_members: tuple[str, ...]
    standings: tuple[Standing, ...]
    found_common: int
    no_place_comes_close: bool
    chance: str

    def with_status(self, status: str) -> tuple[Standing, ...]:
        return tuple(s for s in self.standings if s.status == status)

    @property
    def picks(self) -> tuple[Standing, ...]:
        return self.with_status("common")[:PICKS_SHOWN]


def upper_half_ids(ranking, size: int) -> frozenset[str]:
    table = _Table(ranking, size)
    return frozenset(entity_id for entity_id in table.by_id if table.inside(entity_id))


def _members_of(entity_id: str, tables: Mapping[str, _Table], size: int) -> tuple[MemberStanding, ...]:
    out = []
    for member, table in tables.items():
        item = table.by_id.get(entity_id)
        rank = None if item is None else item.rank
        affinity = None if item is None else item.affinity
        out.append(MemberStanding(
            member=member,
            rank=rank,
            bar=bar_length(rank, size),
            affinity=affinity,
            band=band(affinity),
            in_upper_half=table.inside(entity_id),
            ranked=item is not None,
        ))
    return tuple(out)


def _placed_by(keys: Sequence[tuple[int, int, int]], index: int) -> str:
    """Which of the three orderings separated this place from the one below it (above it, for the last)."""
    if len(keys) == 1:
        return "worst_rank"
    other = keys[index + 1] if index + 1 < len(keys) else keys[index - 1]
    mine = keys[index]
    if mine[0] != other[0]:
        return "worst_rank"
    if mine[1] != other[1]:
        return "sum_of_ranks"
    return "group_position"


def evaluate(long_list: Sequence[str], rankings: Mapping[str, object], members: Sequence[str]) -> Evaluation:
    """Standing of every place in the long list for the members ranked so far.

    `long_list` is the group search's ids in Qloo's order; `rankings` maps each ranked member to a
    records.Ranking, in the order they were ranked; `members` is everyone in the outing.
    """
    size = len(long_list)
    tables = {member: _Table(ranking, size) for member, ranking in rankings.items()}
    k = len(tables)
    most_left_out = max(1, k // 2)

    common, near, rest = [], [], []
    for position, entity_id in enumerate(long_list, 1):
        standings = _members_of(entity_id, tables, size)
        left_out = tuple(s.member for s in standings if not s.in_upper_half)
        if not left_out:
            ranks = [s.rank for s in standings]
            common.append((max(ranks), sum(ranks), position, entity_id, standings))
        elif len(left_out) <= most_left_out:
            worst = max(s.rank or size + 1 for s in standings if not s.in_upper_half)
            near.append((len(left_out), worst, position, entity_id, standings, left_out))
        else:
            rest.append((position, entity_id, standings, left_out))

    common.sort(key=lambda row: row[:3])
    near.sort(key=lambda row: row[:3])
    keys = [row[:3] for row in common]

    ordered = [
        Standing(row[3], row[2], "common", row[4], (), _placed_by(keys, i)) for i, row in enumerate(common)
    ]
    ordered += [Standing(row[3], row[2], "near", row[4], row[5], None) for row in near[:NEAR_SHOWN]]
    leftover = [(row[2], row[3], row[4], row[5]) for row in near[NEAR_SHOWN:]] + rest
    leftover.sort(key=lambda row: row[0])
    ordered += [Standing(row[1], row[0], "set_aside", row[2], row[3], None) for row in leftover]

    return Evaluation(
        size=size,
        half=half(size),
        ranked_members=tuple(tables),
        unranked_members=tuple(m for m in members if m not in tables),
        standings=tuple(ordered),
        found_common=len(common),
        no_place_comes_close=not common and not near,
        chance=chance_line(size, k, len(common)),
    )


def lean_by_member(
    influence: Mapping[str, float], member_entities: Mapping[str, Sequence[str]]
) -> dict[str, float]:
    """Qloo's aggregate influence, summed per member over that member's resolved favourites."""
    return {
        member: round(sum(influence.get(e, 0.0) for e in ids), 6) for member, ids in member_entities.items()
    }


def order_by_lean(members: Sequence[str], lean: Mapping[str, float] | None) -> list[str]:
    """Least led-on first; listed order when there is no lean or two members tie."""
    if not lean:
        return list(members)
    return sorted(members, key=lambda member: lean.get(member, 0.0))


def because_lines(because: Sequence[tuple[str, float]], favourite_of: Mapping[str, str]) -> list[dict]:
    """Qloo's explainability scores that name one of this member's favourites, at or above EXPLAIN_MIN."""
    lines = [
        {"favourite": favourite_of[entity_id], "score": score}
        for entity_id, score in because
        if entity_id in favourite_of and score >= EXPLAIN_MIN
    ]
    return sorted(lines, key=lambda line: -line["score"])
