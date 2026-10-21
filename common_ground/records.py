"""The only module that reads the shape of a Qloo response.

Every reader turns a decoded response into plain records, drops nothing silently, and refuses a shape
the documentation did not describe (`qloo_unexpected_shape`, naming the JSON path, never a value). An
empty result list is `qloo_no_results`. Each shape below is unverified until the key-day probe has seen
a real response (measured.RESPONSE_SHAPES).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from . import measured
from .refusal import Refusal

NO_RESULTS = "qloo_no_results"
UNEXPECTED_SHAPE = "qloo_unexpected_shape"
PERSON = "urn:entity:person"
INFLUENCE_KEY = "signal.interests.entities"

_MISSING = object()


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    name: str
    type: str
    popularity: float | None
    disambiguation: str | None


@dataclass(frozen=True)
class Search:
    candidates: tuple[Candidate, ...]
    dropped_people: int


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    type: str


@dataclass(frozen=True)
class Place:
    entity_id: str
    name: str
    type: str | None
    subtype: str | None
    tags: tuple[Tag, ...]
    address: str | None
    website: str | None
    position: int


@dataclass(frozen=True)
class GroupSearch:
    places: tuple[Place, ...]
    influence: dict[str, float] | None


@dataclass(frozen=True)
class Ranked:
    entity_id: str
    rank: int
    affinity: float | None
    because: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Ranking:
    ranked: tuple[Ranked, ...]
    requested: int
    unrequested: int
    non_increasing: bool

    @property
    def returned_share(self) -> float:
        return len(self.ranked) / self.requested if self.requested else 0.0


def _shape(path: str) -> Refusal:
    return Refusal(UNEXPECTED_SHAPE, path)


def _dict(node: Any, path: str) -> dict:
    if not isinstance(node, dict):
        raise _shape(path)
    return node


def _list(node: Any, path: str) -> list:
    if not isinstance(node, list):
        raise _shape(path)
    return node


def _text(node: dict, key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value:
        raise _shape(f"{path}.{key}")
    return value


def _optional_text(node: dict, key: str, path: str) -> str | None:
    value = node.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _shape(f"{path}.{key}")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _shape(path)
    return float(value)


def _unit(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise _shape(path)
    return float(value)


def _dig(node: Any, steps: Sequence[str] | None) -> Any:
    if steps is None:
        return _MISSING
    for step in steps:
        if not isinstance(node, dict) or step not in node:
            return _MISSING
        node = node[step]
    return node


def _influences(node: Any, path: str) -> dict[str, float] | None:
    if node is _MISSING or node is None:
        return None
    node = _dict(node, path)
    if not node:
        return None
    entries = _list(node.get(INFLUENCE_KEY), f"{path}.{INFLUENCE_KEY}")
    found = {}
    for i, item in enumerate(entries):
        where = f"{path}.{INFLUENCE_KEY}[{i}]"
        item = _dict(item, where)
        found[_text(item, "entity_id", where)] = _unit(item.get("score"), f"{where}.score")
    return found or None


def read_search(body: Any) -> Search:
    results = _list(_dict(body, "$").get("results"), "$.results")
    if not results:
        raise Refusal(NO_RESULTS, "search")
    kept, dropped = [], 0
    for i, raw in enumerate(results):
        where = f"$.results[{i}]"
        raw = _dict(raw, where)
        kind = _text(raw, "type", where)
        if kind == PERSON:
            dropped += 1
            continue
        popularity = raw.get("popularity")
        if popularity is not None:
            popularity = _number(popularity, f"{where}.popularity")
        kept.append(Candidate(
            entity_id=_text(raw, "entity_id", where),
            name=_text(raw, "name", where),
            type=kind,
            popularity=popularity,
            disambiguation=_optional_text(raw, "disambiguation", where),
        ))
    if not kept:
        raise Refusal(NO_RESULTS, "every candidate was a person and was dropped")
    return Search(tuple(kept), dropped)


def _read_tag(raw: Any, where: str) -> Tag:
    raw = _dict(raw, where)
    return Tag(
        id=_text(raw, "id", where),
        name=_text(raw, "name", where),
        type=_optional_text(raw, "type", where) or "",
    )


def read_tags(body: Any) -> tuple[Tag, ...]:
    results = _dict(_dict(body, "$").get("results"), "$.results")
    tags = _list(results.get("tags"), "$.results.tags")
    if not tags:
        raise Refusal(NO_RESULTS, "tags")
    return tuple(_read_tag(raw, f"$.results.tags[{i}]") for i, raw in enumerate(tags))


def _entities(body: Any) -> list:
    results = _dict(_dict(body, "$").get("results"), "$.results")
    entities = _list(results.get("entities"), "$.results.entities")
    if not entities:
        raise Refusal(NO_RESULTS, "entities")
    return entities


def _affinity(raw: dict, where: str) -> float | None:
    value = _dig(raw, measured.AFFINITY_PATH)
    if value is _MISSING:
        return None
    return _unit(value, f"{where}.{'.'.join(measured.AFFINITY_PATH)}")


def _because(raw: dict, where: str) -> tuple[tuple[str, float], ...]:
    found = _influences(_dig(raw, measured.EXPLAIN_PATH), f"{where}.{'.'.join(measured.EXPLAIN_PATH or ())}")
    return tuple(found.items()) if found else ()


def read_group_search(body: Any) -> GroupSearch:
    places = []
    for i, raw in enumerate(_entities(body), 1):
        where = f"$.results.entities[{i - 1}]"
        raw = _dict(raw, where)
        properties = raw.get("properties")
        properties = {} if properties is None else _dict(properties, f"{where}.properties")
        tags = raw.get("tags")
        tags = () if tags is None else tuple(
            _read_tag(t, f"{where}.tags[{j}]") for j, t in enumerate(_list(tags, f"{where}.tags"))
        )
        places.append(Place(
            entity_id=_text(raw, "entity_id", where),
            name=_text(raw, "name", where),
            type=_optional_text(raw, "type", where),
            subtype=_optional_text(raw, "subtype", where),
            tags=tags,
            address=_optional_text(properties, "address", f"{where}.properties"),
            website=_optional_text(properties, "website", f"{where}.properties"),
            position=i,
        ))
    lean_path = ".".join(measured.LEAN_PATH or ())
    return GroupSearch(tuple(places), _influences(_dig(body, measured.LEAN_PATH), f"$.{lean_path}"))


def read_ranking(body: Any, requested: Sequence[str]) -> Ranking:
    """One member's ranking of the long list. Ids that were not asked for are counted and set aside."""
    asked = set(requested)
    seen: set[str] = set()
    ranked: list[Ranked] = []
    unrequested = 0
    for i, raw in enumerate(_entities(body)):
        where = f"$.results.entities[{i}]"
        raw = _dict(raw, where)
        entity_id = _text(raw, "entity_id", where)
        if entity_id not in asked:
            unrequested += 1
            continue
        if entity_id in seen:
            continue
        seen.add(entity_id)
        ranked.append(Ranked(entity_id, len(ranked) + 1, _affinity(raw, where), _because(raw, where)))
    present = [r.affinity for r in ranked if r.affinity is not None]
    non_increasing = all(a >= b for a, b in zip(present, present[1:]))
    return Ranking(tuple(ranked), len(asked), unrequested, non_increasing)


_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,47}$")
_HEX_RUN = re.compile(r"^[0-9a-fA-F]{24,}$")


def _safe_key(key: str) -> str:
    return key if _SAFE_KEY.match(key) and not _HEX_RUN.match(key) else "<key>"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def skeleton(body: Any) -> dict[str, tuple[str, int]]:
    """JSON paths with the types seen there and how many times: no value, and no key that looks like an id."""
    found: dict[str, dict[str, int]] = {}

    def walk(node: Any, path: str) -> None:
        kinds = found.setdefault(path, {})
        kinds[_kind(node)] = kinds.get(_kind(node), 0) + 1
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{_safe_key(str(key))}")
        elif isinstance(node, list):
            for item in node:
                walk(item, f"{path}[]")

    walk(body, "$")
    return {path: ("|".join(sorted(kinds)), sum(kinds.values())) for path, kinds in found.items()}
