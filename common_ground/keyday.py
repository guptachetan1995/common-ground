"""The key-day probe: P1 to P6, at most 14 live calls and never a retry.

It prints shapes only: JSON paths with their types and counts, status codes, counts and scales, the
thresholds T1 to T5 as pass or fail, and a block of constants for measured.py. No id, name or response
string is ever printed; everything shown is a count, a code this app named, or vocabulary of its own.
The key travels only through wire.send.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from . import fair_share, measured, qloo_calls, records, wire
from .refusal import Refusal

CALL_CAP = 14
ENOUGH_PLACES = 30
MIN_PLACES = 10
DISTINCT_PLACES = 3
FALLBACK_IDS = 25
DAY = "friday"
PRICES = (2, 3)
DOMAINS = (("restaurant", "urn:entity:place"), ("band", "urn:entity:artist"), ("film", "urn:entity:movie"))
WRONG_KEY = "not-a-key"
SHOWN_PATHS = 60
ENTITY = "$.results.entities[]."
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class BudgetSpent(Exception):
    pass


@dataclass
class _Call:
    status: int
    code: str | None
    body: Any
    shape: dict[str, tuple[str, int]]


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    passed: dict[str, bool] = field(default_factory=dict)
    calls: int = 0
    block: str | None = None

    def render(self) -> str:
        return "\n".join(self.lines)


def _id_form(identifier: str) -> str:
    if _UUID.match(identifier):
        return "uuid"
    if identifier.startswith("urn:tag:"):
        return f"urn:tag with {identifier.count(':') + 1} segments"
    return "other"


def _count(skel: dict[str, tuple[str, int]], path: str) -> int:
    return skel.get(path, ("", 0))[1]


def _locate(
    skel: dict, prefix: str, leaf: str, default: Sequence[str] | None, nested: bool = True
) -> tuple | None:
    """Where a field sits: the documented path if it is there, else any path ending in the field's name."""
    if default is not None and _count(skel, prefix + ".".join(default)) > 0:
        return tuple(default)
    hits = sorted(
        p for p in skel
        if p.startswith(prefix) and p.rsplit(".", 1)[-1] == leaf and skel[p][1] > 0
        and (nested or "[]" not in p)
    )
    return tuple(hits[0][len(prefix):].split(".")) if hits else None


class _Probe:
    def __init__(self, favourites: Sequence[str], key: str, base_url: str, send: Callable) -> None:
        self.favourites = list(favourites)
        self.key = key
        self.base_url = base_url
        self.send = send
        self.calls = 0
        self.report = Report()
        self.matches: list[records.Candidate] = []
        self.facts: dict[str, Any] = {"readers": set()}

    def say(self, text: str) -> None:
        self.report.lines.append(text)

    def call(self, request: qloo_calls.Request, key: str | None = None) -> _Call:
        if self.calls >= CALL_CAP:
            raise BudgetSpent
        self.calls += 1
        try:
            reply = self.send(request, key or self.key, base_url=self.base_url)
        except wire.QlooError as error:
            return _Call(error.status, error.code, None, error.shape)
        except Refusal as error:
            return _Call(0, error.code, None, {})
        return _Call(reply.status, None, reply.body, {})

    def read(self, call: _Call, reader: Callable, *args: Any) -> tuple[Any, str | None]:
        if call.code:
            return None, call.code
        try:
            return reader(call.body, *args), None
        except Refusal as error:
            where = f" at {error.detail}" if error.code == records.UNEXPECTED_SHAPE else ""
            return None, error.code + where

    def shape(self, label: str, call: _Call) -> None:
        skel = records.skeleton(call.body) if call.body is not None else call.shape
        self.say(f"shape of {label}: {len(skel)} paths")
        for path in sorted(skel)[:SHOWN_PATHS]:
            kind, count = skel[path]
            self.say(f"  {path}: {kind} x{count}")

    def status(self, call: _Call) -> str:
        return str(call.status) if call.status else "no answer"

    def go(self) -> None:
        if self.p1():
            tag = self.p2()
            self.p3_to_p5(tag)
            self.p6(wrong_key=False)
        else:
            self.p6(wrong_key=True)

    def p1(self) -> bool:
        self.say("P1 /search, three names, types in the comma form")
        resolved = True
        for (label, implied), name in zip(DOMAINS, self.favourites):
            call = self.call(qloo_calls.search_request(name))
            found, code = self.read(call, records.read_search)
            if not found:
                self.say(f"  {label}: status {self.status(call)}, refused {code}")
                resolved = False
                continue
            top = found.candidates[0]
            self.matches.append(top)
            as_implied = top.type == implied
            self.facts.setdefault("types_as_implied", []).append(as_implied)
            self.say(
                f"  {label}: status {self.status(call)}, {len(found.candidates)} candidates, "
                f"top candidate has the implied type: {'yes' if as_implied else 'no'}, "
                f"popularity on {sum(c.popularity is not None for c in found.candidates)}, "
                f"disambiguation on {sum(c.disambiguation is not None for c in found.candidates)}, "
                f"people dropped {found.dropped_people}"
            )
            if not self.facts.get("search_shown"):
                self.facts["search_shown"] = True
                self.shape("/search", call)
        self.facts["p1_ok"] = resolved and len(self.matches) == len(DOMAINS)
        if self.facts["p1_ok"]:
            self.facts["readers"].add("search")
        return self.facts["p1_ok"]

    def p2(self) -> dict | None:
        call = self.call(qloo_calls.tags_request("restaurant"))
        found, code = self.read(call, records.read_tags)
        if not found:
            self.say(f"P2 /v2/tags: status {self.status(call)}, refused {code}")
            return None
        self.facts["readers"].add("tags")
        chosen = next((t for t in found if t.name.lower() == "restaurant"), None) or next(
            (t for t in found if "restaurant" in t.name.lower()), None
        )
        self.say(
            f"P2 /v2/tags: status {self.status(call)}, {len(found)} tags, a restaurant kind found: "
            f"{'yes' if chosen else 'no'}" + (f", its id form: {_id_form(chosen.id)}" if chosen else "")
        )
        self.shape("/v2/tags", call)
        return {"id": chosen.id, "name": chosen.name} if chosen else None

    def conditions(self, city: str, tag: dict | None) -> dict:
        return {
            "placeText": city, "day": DAY, "priceMin": PRICES[0], "priceMax": PRICES[1],
            "radiusM": None, "kindTag": tag,
        }

    def p3_to_p5(self, tag: dict | None) -> None:
        anchors = [m.entity_id for m in self.matches]
        best = None
        for number, city in enumerate((measured.SAMPLE_CITY, measured.FALLBACK_CITY), 1):
            cond = self.conditions(city, tag)
            call = self.call(qloo_calls.group_search_request(cond, anchors))
            group, code = self.read(call, records.read_group_search)
            places = len(group.places) if group else 0
            self.say(
                f"P3 group search, city {number}: status {self.status(call)}, {places} places"
                + (f", refused {code}" if code else "")
            )
            if best is None or places > best[4]:
                best = (city, cond, call, group, places)
            if places >= ENOUGH_PLACES:
                break
        city, cond, call, group, places = best
        self.facts.update(city=city, places=places, tag=tag)
        if not group:
            return
        self.facts["readers"].add("group_search")
        self.facts["group"], self.facts["cond"] = group, cond
        self.p3_facts(call, group, tag)
        ids = [p.entity_id for p in group.places]
        self.p4(anchors, cond, tag, ids, city)
        if self.facts.get("location_works") is not False:
            self.p5(cond, ids)

    def p3_facts(self, call: _Call, group: records.GroupSearch, tag: dict | None) -> None:
        skel = records.skeleton(call.body)
        n = len(group.places)
        are_places = sum(
            p.type == qloo_calls.PLACE or (p.subtype or "").startswith(qloo_calls.PLACE) for p in group.places
        )
        with_tag = sum(any(t.id == tag["id"] for t in p.tags) for p in group.places) if tag else 0
        affinity = _locate(skel, ENTITY, "affinity", measured.AFFINITY_PATH)
        explain = _locate(skel, ENTITY, "explainability", measured.EXPLAIN_PATH)
        lean = _locate(skel, "$.", "explainability", measured.LEAN_PATH, nested=False)
        self.facts.update(explain_path=explain, lean_path=lean, kind_share=with_tag / n if tag else None)
        self.say(
            f"P3 facts: of type place {are_places} of {n}; "
            f"affinity {'at ' + '.'.join(affinity) if affinity else 'absent'}"
            f" on {_count(skel, ENTITY + '.'.join(affinity)) if affinity else 0}; "
            f"distance on {_count(skel, ENTITY + 'query.distance')}; "
            f"explainability per result {'at ' + '.'.join(explain) if explain else 'absent'}; "
            f"aggregate {'at ' + '.'.join(lean) if lean else 'absent'}; "
            f"locality signal {'present' if _count(skel, '$.query.locality.signal') else 'absent'}; "
            f"address on {sum(p.address is not None for p in group.places)}, "
            f"website on {sum(p.website is not None for p in group.places)}; "
            f"carrying the kind tag {with_tag if tag else 'not tested (no kind tag)'}"
        )
        self.shape("/v2/insights, group search", call)

    def p4(self, anchors: list[str], cond: dict, tag: dict | None, ids: list[str], city: str) -> None:
        base = set(ids)
        variants = (
            ("location", {**cond, "placeText": None}),
            ("day", {**cond, "day": None}),
            ("price", {**cond, "priceMin": None, "priceMax": None}),
        )
        self.say("P4 each condition changes the result")
        for name, changed in variants:
            request = qloo_calls.group_search_request(changed, anchors)
            call = self.call(request)
            group, code = self.read(call, records.read_group_search)
            differs = None if group is None else {p.entity_id for p in group.places} != base
            self.facts[f"{name}_works"] = differs
            verdict = {None: "no usable answer", True: "a different set", False: "the same set"}[differs]
            self.say(f"  without {name}: status {self.status(call)}, {verdict}")
            if name == "location" and differs is False:
                self.geocode_fallback(request, {p.entity_id for p in group.places}, city)

    def geocode_fallback(self, without: qloo_calls.Request, unlocated: set[str], city: str) -> None:
        if self.calls >= CALL_CAP:
            self.say("  the geocode fallback was not tried: the call budget is spent")
            return
        call = self.call(qloo_calls.add_param(without, "filter.geocode.name", city))
        group, _ = self.read(call, records.read_group_search)
        works = group is not None and {p.entity_id for p in group.places} != unlocated
        self.facts["geocode_works"] = works
        self.facts["location_works"] = works
        self.say(
            f"  location by the geocode name instead: status {self.status(call)}, "
            f"{'works' if works else 'ignored too'}"
        )

    def pair(self, ids: list[str], cond: dict) -> list[tuple[_Call, records.Ranking | None]]:
        out = []
        for member in self.matches[1:]:
            call = self.call(qloo_calls.ranking_request(cond, [member.entity_id], ids))
            ranking, code = self.read(call, records.read_ranking, ids)
            out.append((call, ranking))
            if ranking:
                affinities = [r.affinity for r in ranking.ranked if r.affinity is not None]
                scale = f"{min(affinities):.1f} to {max(affinities):.1f}" if affinities else "none"
                self.say(
                    f"  a member's ranking of {len(ids)} ids: status {self.status(call)}, returned "
                    f"{len(ranking.ranked)} ({ranking.returned_share:.0%}), "
                    f"not requested {ranking.unrequested}, "
                    f"non-increasing {'yes' if ranking.non_increasing else 'no'}, affinity scale {scale}"
                )
            else:
                self.say(
                    f"  a member's ranking of {len(ids)} ids: status {self.status(call)}, refused {code}"
                )
        return out

    @staticmethod
    def accepted(results: list) -> bool:
        return all(r is not None and r.returned_share >= fair_share.MIN_RANKED_SHARE for _, r in results)

    def p5(self, cond: dict, ids: list[str]) -> None:
        self.say("P5 two members' rankings, exactly as the comparison will ask for them")
        used = ids
        results = self.pair(ids, cond)
        if not self.accepted(results) and len(ids) > FALLBACK_IDS and self.calls + 2 <= CALL_CAP:
            self.say(f"  not accepted at {len(ids)} ids: the same two calls at {FALLBACK_IDS}")
            used = ids[:FALLBACK_IDS]
            results = self.pair(used, cond)
        rankings = [r for _, r in results]
        self.facts.update(p5_ids=len(used), p5_accepted=self.accepted(results), p5_results=results)
        if not self.accepted(results):
            return
        self.facts["readers"].add("ranking")
        first, second = (fair_share.upper_half_ids(r, len(used)) for r in rankings)
        distinct = len(first - second)
        self.facts.update(
            p5_clean=all(r.unrequested == 0 and r.non_increasing for r in rankings),
            p5_distinct=distinct >= DISTINCT_PLACES,
        )
        self.say(f"  the two upper halves differ in {distinct} places")
        skel = records.skeleton(results[0][0].body)
        self.facts["affinity_path"] = _locate(skel, ENTITY, "affinity", measured.AFFINITY_PATH)
        self.shape("/v2/insights, one member's ranking", results[0][0])

    def p6(self, wrong_key: bool) -> None:
        if wrong_key:
            call = self.call(qloo_calls.tags_request("restaurant"), key=WRONG_KEY)
            label = "P6 a deliberately wrong key"
        else:
            call = self.call(qloo_calls.unsupported_type_request())
            label = "P6 an unsupported filter.type"
        self.say(f"{label}: status {self.status(call)}, named {call.code}")
        if call.shape:
            self.shape("the error body", _Call(call.status, call.code, None, call.shape))


def _verdicts(p: _Probe) -> dict[str, tuple[bool, str]]:
    f = p.facts
    location = f.get("location_works") is not False and f.get("location_works") is not None
    t1 = f.get("places", 0) >= MIN_PLACES and location
    t3 = bool(f.get("p5_accepted") and f.get("p5_clean") and f.get("p5_distinct"))
    return {
        "T1": (t1, f"{f.get('places', 0)} places for the sample group's conditions; the location filter "
                   f"{'works' if location else 'was not shown to work'}"),
        "T2": (location, "day filter " + ("works" if f.get("day_works") else "ignored or untested")
                         + ", price filter " + ("works" if f.get("price_works") else "ignored or untested")),
        "T3": (t3, f"tested at {f.get('p5_ids', 0)} ids"),
        "T4": (f.get("explain_path") is not None, "explainability per result "
               + ("present" if f.get("explain_path") else "absent")),
        "T5": (
            f.get("affinity_path") is not None,
            "affinity " + ("present" if f.get("affinity_path") else "absent"),
        ),
    }


def _scale(ranking: records.Ranking | None) -> tuple[float, float] | None:
    values = [r.affinity for r in ranking.ranked if r.affinity is not None] if ranking else []
    return (round(min(values), 1), round(max(values), 1)) if values else None


def _names(names) -> str:
    return "frozenset({" + ", ".join(repr(n) for n in sorted(names)) + "})" if names else "frozenset()"


def _block(p: _Probe) -> str:
    """The lines that replace measured.py's defaults, and the names still unverified after this run."""
    f = p.facts
    group = f["group"]
    fixed = {"SAMPLE_CITY", "AFFINITY_PATH", "EXPLAIN_PATH", "LEAN_PATH", "AFFINITY_SCALE"}
    if f["p1_ok"]:
        fixed.add("TYPES_FORM")
        if all(f["types_as_implied"]):
            fixed.add("FAVOURITE_TYPES")
    kind_tested = f["tag"] is not None
    spelled = {
        "location": "filter.geocode.name" if f.get("geocode_works") else "filter.location.query",
        "day": "filter.hours" if f.get("day_works") else None,
        "price": "filter.price_level" if f.get("price_works") else None,
        "kind": "filter.tags" if not kind_tested or f["kind_share"] >= fair_share.MIN_RANKED_SHARE else None,
    }
    if kind_tested and f.get("day_works") is not None and f.get("price_works") is not None:
        fixed.add("CONDITIONS_OK")
    fell_back = f["p5_ids"] == FALLBACK_IDS and len(group.places) > FALLBACK_IDS
    long_list = FALLBACK_IDS if fell_back else measured.LONG_LIST
    if f["p5_ids"] == long_list:
        fixed.add("LONG_LIST")
    scales = [_scale(ranking) for _, ranking in f["p5_results"]]
    if f["readers"] >= {"search", "tags", "group_search", "ranking"}:
        fixed.add("RESPONSE_SHAPES")
    lines = [
        f"FAVOURITE_TYPES = {measured.FAVOURITE_TYPES!r}",
        f"TYPES_FORM = {measured.TYPES_FORM!r}",
        f"CONDITIONS_OK = {spelled!r}",
        f"SAMPLE_CITY = {f['city']!r}",
        f"LONG_LIST = {long_list}",
        f"AFFINITY_PATH = {f['affinity_path']!r}",
        f"EXPLAIN_PATH = {f['explain_path']!r}",
        f"LEAN_PATH = {f['lean_path']!r}",
        f"AFFINITY_SCALE = {tuple(scales)!r}" if all(scales) else "AFFINITY_SCALE = None",
        f"RESPONSE_SHAPES = {_names(f['readers'])}",
        f"UNVERIFIED = {_names(set(measured.UNVERIFIED) - fixed)}",
    ]
    return "\n".join(lines)


def run(
    favourites: Sequence[str], key: str, *, base_url: str = wire.BASE_URL, send: Callable = wire.send
) -> Report:
    """Run the probe. `favourites` are a restaurant, a band and a film, in that order."""
    probe = _Probe(favourites, key, base_url, send)
    try:
        probe.go()
    except BudgetSpent:
        probe.say(f"stopped: the {CALL_CAP}-call budget is spent")
    report = probe.report
    report.calls = probe.calls
    verdicts = _verdicts(probe)
    report.passed = {name: ok for name, (ok, _) in verdicts.items()}
    probe.say(f"calls made: {probe.calls} of {CALL_CAP}")
    for name, (ok, why) in verdicts.items():
        probe.say(f"{name} {'PASS' if ok else 'FAIL'}: {why}")
    if report.passed["T1"] and report.passed["T3"] and report.passed["T2"]:
        report.block = _block(probe)
        probe.say("constants for measured.py (K2 pastes these):")
        probe.say(report.block)
    else:
        probe.say("no constants block: T1 to T3 did not all pass, and a T1 or T3 failure stops the entry")
    return report
