"""The comparison: one group search, then one ranking per person, stopping as soon as the answer is known.

Qloo applies the group's conditions inside the group search, so every place it returns already meets them;
that list (the long list) is then ranked once for each person on that person's favourites alone. The rule
that turns ranks into `common`, `near` and `set_aside` is fair_share's; this module spends the calls, keeps
the trace and writes the result into the outing. A comparison that is not stale is resumed, never repeated:
it keeps the long list and the rankings it already has and asks only for the people still unranked.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import fair_share, outings, qloo_calls, records, wire
from .refusal import Refusal

DONE = "done"
NO_COMMON_GROUND = "no_common_ground"
THIN_LIST = "thin_list"
QLOO_REFUSED = "qloo_refused"
LIMIT_STOPS = ("over_limit", "agent_allowance_spent", "daily_ceiling_spent")
TRANSIENT = (wire.RATE_LIMITED, wire.UNAVAILABLE)
CONSECUTIVE_REFUSALS = 2
AGENT = "agent"


class _State:
    """What a run has learned so far. It is filled in as calls return, so a run cut short still has it."""

    def __init__(self) -> None:
        self.known = False
        self.thin = False
        self.long_ids: list[str] = []
        self.static: dict[str, dict] = {}
        self.lean: dict[str, float] | None = None
        self.rankings: dict[str, records.Ranking] = {}
        self.because: dict[str, dict[str, list]] = {}
        self.partial: dict[str, dict] = {}
        self.stopped: str | None = None
        self.saved = 0


def _ready(out: Mapping) -> None:
    missing = outings.members_without_a_match(out)
    if missing:
        raise Refusal("needs_favourites", ", ".join(missing))
    pending = [f"{m['id']}.{f['id']}" for m in out["members"] for f in m["favourites"]
               if f["candidates"] and not f["resolved"]]
    if pending:
        raise Refusal("favourite_unresolved", ", ".join(pending))


def _resume(out: Mapping, state: _State) -> None:
    """Take the long list and the rankings back from the stored places."""
    state.known = True
    comparison = out["comparison"]
    state.thin = comparison["thin"]
    state.long_ids = list(out["longList"]["ids"]) if out["longList"] else []
    state.lean = out["longList"]["lean"] if out["longList"] else None
    state.static = {p["entityId"]: p for p in out["places"]}
    state.partial = dict(comparison["partial"])
    for member_id in comparison["rankedMembers"]:
        rows = sorted(
            ((p["entityId"], pm) for p in out["places"] for pm in p["perMember"]
             if pm["member"] == member_id and pm["ranked"]),
            key=lambda row: row[1]["rank"],
        )
        fields = [(entity_id, *(pm[k] for k in ("rank", "affinity"))) for entity_id, pm in rows]
        state.rankings[member_id] = records.Ranking(
            tuple(records.Ranked(entity_id, rank, affinity, ()) for entity_id, rank, affinity in fields),
            len(state.long_ids), 0, True,
        )
        state.because[member_id] = {entity_id: pm["because"] for entity_id, pm in rows}
    state.stopped = comparison["stoppedBecause"]
    state.saved = out["budget"]["saved"]


def _group_search(out: Mapping, spend, state: _State) -> None:
    ids = outings.all_resolved_ids(out)
    request = qloo_calls.group_search_request(out["conditions"], ids)
    because = (
        f"one search for the whole group: {len(ids)} resolved favourites as the signal, "
        "with the day, price, city and kind applied inside Qloo"
    )
    try:
        group = spend.call(request, because, read=records.read_group_search)
    except Refusal as error:
        if error.code != records.NO_RESULTS:
            raise
        group = records.GroupSearch((), None)
    state.known = True
    state.long_ids = [p.entity_id for p in group.places]
    state.static = {
        p.entity_id: {
            "entityId": p.entity_id, "name": p.name, "listPosition": p.position,
            "tags": [t.name for t in p.tags], "address": p.address, "website": p.website,
        }
        for p in group.places
    }
    state.lean = (
        fair_share.lean_by_member(group.influence, outings.member_entities(out)) if group.influence else None
    )
    if len(group.places) < fair_share.MIN_LONG_LIST:
        state.thin = True
        state.stopped = THIN_LIST
        state.saved = len(out["members"])
        spend.note(
            f"Qloo returned {len(group.places)} places, fewer than the {fair_share.MIN_LONG_LIST} needed to "
            f"compare people; the {state.saved} rankings were not spent and widening is the organiser's"
        )


def _common_count(state: _State, member_ids: list[str]) -> int:
    return fair_share.evaluate(state.long_ids, state.rankings, member_ids).found_common


def _lean_reason(state: _State, name: str, member_id: str, place: int, total: int) -> str:
    if state.lean:
        return (f"{name}'s favourites led the group search least (lean {state.lean[member_id]:.2f}), "
                f"so they are ranked {_ordinal(place)} of {total}")
    return f"{name} is ranked {_ordinal(place)} of {total} in listed order, since Qloo gave no explainability"


def _ordinal(n: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}[n]


def _rank(out: Mapping, spend, state: _State, member: Mapping, reason: str) -> records.Ranking:
    request = qloo_calls.ranking_request(out["conditions"], outings.resolved_ids(member), state.long_ids)
    because = f"{member['name']}'s own ranking of the {len(state.long_ids)} places; {reason}"
    try:
        return spend.call(
            request, because, member=member["id"],
            read=lambda body: records.read_ranking(body, state.long_ids),
        )
    except Refusal as error:
        if error.code != records.NO_RESULTS:
            raise
        return records.Ranking((), len(state.long_ids), 0, True)


def _rankings(out: Mapping, spend, state: _State, complete: bool) -> None:
    members = {m["id"]: m for m in out["members"]}
    member_ids = list(members)
    order = fair_share.order_by_lean(member_ids, state.lean)
    todo = [m for m in order if m not in state.rankings]
    state.saved = 0
    refused: list[str] = []
    in_a_row = 0
    while todo:
        if state.rankings and not complete and not _common_count(state, member_ids):
            state.stopped = NO_COMMON_GROUND
            state.saved = len(todo)
            spend.note(
                f"no place is shared by everyone after ranking {_list(members, state.rankings)}; no later "
                f"ranking can bring one back, so the ranking for {_list(members, todo)} was not spent "
                f"({state.saved} saved)"
            )
            return
        member = members[todo.pop(0)]
        reason = _lean_reason(state, member["name"], member["id"], order.index(member["id"]) + 1, len(order))
        try:
            ranking = _rank(out, spend, state, member, reason)
        except Refusal as error:
            if error.code in LIMIT_STOPS:
                state.stopped = error.code
                spend.note(
                    f"stopped by {error.code} ({error.detail}); the ranking for "
                    f"{_list(members, [member['id'], *todo])} was not made"
                )
                return
            if error.code not in TRANSIENT:
                raise
            refused.append(member["id"])
            in_a_row += 1
            if in_a_row == CONSECUTIVE_REFUSALS:
                state.stopped = QLOO_REFUSED
                spend.note(f"Qloo refused {CONSECUTIVE_REFUSALS} rankings in a row after retrying; stopping")
                return
            continue
        in_a_row = 0
        state.rankings[member["id"]] = ranking
        favourite_of = outings.favourite_by_entity(member)
        state.because[member["id"]] = {
            r.entity_id: fair_share.because_lines(r.because, favourite_of) for r in ranking.ranked
        }
        if ranking.returned_share < fair_share.MIN_RANKED_SHARE:
            state.partial[member["id"]] = {"ranked": len(ranking.ranked), "of": len(state.long_ids)}
            spend.note(
                f"Qloo ranked only {len(ranking.ranked)} of {len(state.long_ids)} places "
                f"for {member['name']}",
                member=member["id"],
            )
    if refused:
        state.stopped = QLOO_REFUSED
        spend.note(f"Qloo refused the ranking for {_list(members, refused)}; the others are done")
    else:
        state.stopped = DONE
        spend.note("every member is ranked")


def _list(members: Mapping, ids) -> str:
    names = [members[i]["name"] for i in ids]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _build(out: Mapping, state: _State) -> tuple[list[dict], dict]:
    """The places and the comparison summary for the state so far, in the shapes the outing stores."""
    member_ids = [m["id"] for m in out["members"]]
    index = {m: i for i, m in enumerate(member_ids)}
    organiser_for = {
        m["id"]: any(f["resolved"] and f["resolvedBy"] == "organiser_for" for f in m["favourites"])
        for m in out["members"]
    }
    ruled = {p["entityId"]: p["ruledOut"]["reason"] for p in out["places"] if p["status"] == "ruled_out"}
    evaluation = (
        fair_share.evaluate(state.long_ids, state.rankings, member_ids) if state.rankings else None
    )

    def place(entity_id: str, status: str, placed_by: str | None, left_out, members) -> dict:
        built = {
            **{k: v for k, v in state.static[entity_id].items() if k in
               ("entityId", "name", "listPosition", "tags", "address", "website")},
            "status": status,
            "placedBy": placed_by,
            "leftOut": list(left_out),
            "perMember": sorted((
                {
                    "member": s.member, "rank": s.rank, "bar": round(s.bar, 4), "affinity": s.affinity,
                    "band": s.band, "inUpperHalf": s.in_upper_half, "ranked": s.ranked,
                    "because": state.because.get(s.member, {}).get(entity_id, []),
                    "restsOnOrganiserResolution": organiser_for[s.member],
                }
                for s in members
            ), key=lambda row: index[row["member"]]),
        }
        if entity_id in ruled:
            built["ruledOut"] = {"reason": ruled[entity_id], "was": status}
            built["status"] = "ruled_out"
        return built

    if evaluation is None:
        places = [place(e, "set_aside", None, (), ()) for e in state.long_ids]
    else:
        places = [
            place(s.entity_id, s.status, s.placed_by, s.left_out, s.members) for s in evaluation.standings
        ]
    ranked = list(state.rankings)
    unranked = [m for m in member_ids if m not in state.rankings]
    if state.thin:
        outcome = "thin_list"
    elif evaluation is None:
        outcome = "unranked"
    elif evaluation.found_common:
        outcome = "common"
    else:
        outcome = "none_close" if evaluation.no_place_comes_close else "none_shared"
    comparison = {
        "stale": False,
        "complete": not unranked and not state.thin,
        "thin": state.thin,
        "outcome": outcome,
        "size": len(state.long_ids),
        "foundCommon": evaluation.found_common if evaluation else 0,
        "expectedByChance": (
            fair_share.expected_by_chance(len(state.long_ids), len(ranked)) if ranked else None
        ),
        "chance": evaluation.chance if evaluation else None,
        "rankedMembers": ranked,
        "unrankedMembers": unranked,
        "partial": state.partial,
        "stoppedBecause": state.stopped,
    }
    return places, comparison


def _apply(out: dict, state: _State) -> None:
    if state.stopped:
        out["budget"]["stoppedBecause"] = state.stopped
        out["budget"]["saved"] = state.saved
    if not state.known:
        return
    out["longList"] = {"size": len(state.long_ids), "ids": state.long_ids, "lean": state.lean}
    out["places"], out["comparison"] = _build(out, state)


def _summary(out: Mapping, state: _State, spend) -> dict:
    places, comparison = _build(out, state)
    names = {m["id"]: m["name"] for m in out["members"]}

    def line(p: dict) -> dict:
        return {
            "placeId": p["entityId"], "name": p["name"], "status": p["status"], "placedBy": p["placedBy"],
            "ranks": {names[pm["member"]]: pm["rank"] for pm in p["perMember"]},
            "leftOut": [names[m] for m in p["leftOut"]],
        }

    common = [p for p in places if p["status"] == "common"]
    near = [p for p in places if p["status"] == "near"]
    return {
        "outingId": out["id"],
        "outcome": comparison["outcome"],
        "stoppedBecause": state.stopped,
        "complete": comparison["complete"],
        "callsThisRun": spend.calls_this_run,
        "callsSpent": spend.spent,
        "callLimit": spend.limit,
        "saved": state.saved,
        "chance": comparison["chance"],
        "common": [line(p) for p in common[:fair_share.PICKS_SHOWN]],
        "near": [line(p) for p in near],
        "alsoRanked": len(places) - min(len(common), fair_share.PICKS_SHOWN) - len(near),
        "unranked": [names[m] for m in comparison["unrankedMembers"]],
        "partialRankings": {names[m]: v for m, v in comparison["partial"].items()},
        "trace": spend.entries,
    }


def run(out: Mapping, spend, *, complete: bool) -> dict[str, Any]:
    """Compare places for the whole group. Raises a Refusal when nothing could be compared; a run cut short
    by a limit or by Qloo returns what it has, with `stoppedBecause` saying why."""
    _ready(out)
    prior = out["comparison"]
    state = _State()
    spend.also(lambda o: _apply(o, state))
    try:
        if prior is not None and not prior["stale"]:
            _resume(out, state)
        else:
            _group_search(out, spend, state)
        if not state.thin:
            _rankings(out, spend, state, complete)
    except Refusal as error:
        state.stopped = error.code
        raise
    return _summary(out, state, spend)
