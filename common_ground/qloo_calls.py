"""Every request this app can make to Qloo, built from a per-endpoint parameter allowlist.

Qloo ignores a parameter it does not recognise without saying so, so a request is built here or not
at all: a name outside the allowlist, a weight object, or anything but a plain value is refused. All
requests are GET. The key is not part of a request; wire.py adds it to a header.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, urlencode

from . import measured
from .refusal import Refusal

PLACE = "urn:entity:place"
PARAM_REFUSED = "param_refused"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

SEARCH_PARAMS = frozenset({"query", "types", "take"})
TAG_PARAMS = frozenset({"filter.query", "take"})
PLACE_PARAMS = frozenset({
    "filter.type",
    "signal.interests.entities",
    "filter.exclude.entities",
    "filter.results.entities",
    "filter.location.query",
    "filter.location.radius",
    "filter.geocode.name",
    "filter.geocode.country_code",
    "filter.hours",
    "filter.price_level.min",
    "filter.price_level.max",
    "filter.tags",
    "feature.explainability",
    "take",
})
INSIGHTS_BY_TYPE = {PLACE: PLACE_PARAMS}


@dataclass(frozen=True)
class Request:
    path: str
    params: tuple[tuple[str, str], ...]

    def query_string(self) -> str:
        return urlencode(self.params, safe=",:", quote_via=quote)

    def as_dict(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for name, value in self.params:
            merged[name] = f"{merged[name]},{value}" if name in merged else value
        return merged


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, str)):
        return str(value)
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return ",".join(value)
    raise Refusal(PARAM_REFUSED, "a value that is not plain text, a number or a list of ids")


def _checked(path: str, items: Iterable[tuple[str, Any]]) -> Request:
    pairs = [(name, _value(value)) for name, value in items if value is not None]
    if path == "/search":
        allowed = SEARCH_PARAMS
    elif path == "/v2/tags":
        allowed = TAG_PARAMS
    elif path == "/v2/insights":
        kinds = [value for name, value in pairs if name == "filter.type"]
        allowed = INSIGHTS_BY_TYPE.get(kinds[0]) if len(kinds) == 1 else None
        if allowed is None:
            raise Refusal(PARAM_REFUSED, "filter.type")
    else:
        raise Refusal(PARAM_REFUSED, path)
    for name, _ in pairs:
        if name not in allowed:
            raise Refusal(PARAM_REFUSED, name)
    return Request(path, tuple(pairs))


def _condition_pairs(conditions: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The group's conditions as Qloo spells them. A condition left out (or None) is simply not sent."""
    spelled = measured.CONDITIONS_OK
    pairs: list[tuple[str, Any]] = []
    if spelled["location"] and conditions.get("placeText"):
        pairs.append((spelled["location"], conditions["placeText"]))
        if conditions.get("radiusM") is not None and spelled["location"] == "filter.location.query":
            pairs.append(("filter.location.radius", conditions["radiusM"]))
    if spelled["day"] and conditions.get("day"):
        pairs.append((spelled["day"], conditions["day"]))
    if spelled["price"]:
        pairs.append((spelled["price"] + ".min", conditions.get("priceMin")))
        pairs.append((spelled["price"] + ".max", conditions.get("priceMax")))
    if spelled["kind"] and conditions.get("kindTag"):
        pairs.append((spelled["kind"], conditions["kindTag"]["id"]))
    return pairs


def _explain_pairs() -> list[tuple[str, Any]]:
    wanted = measured.EXPLAIN_PATH is not None or measured.LEAN_PATH is not None
    return [("feature.explainability", True)] if wanted else []


def search_request(name: str, take: int = 5) -> Request:
    types = measured.FAVOURITE_TYPES
    kinds = [("types", list(types))] if measured.TYPES_FORM == "comma" else [("types", t) for t in types]
    return _checked("/search", [("query", name), *kinds, ("take", take)])


def tags_request(word: str, take: int = 10) -> Request:
    return _checked("/v2/tags", [("filter.query", word), ("take", take)])


def group_search_request(
    conditions: Mapping[str, Any], entity_ids: Sequence[str], take: int | None = None
) -> Request:
    """Everyone's resolved favourites as the signal, the conditions applied inside Qloo."""
    return _checked("/v2/insights", [
        ("filter.type", PLACE),
        ("signal.interests.entities", list(entity_ids)),
        ("filter.exclude.entities", list(entity_ids)),
        *_condition_pairs(conditions),
        *_explain_pairs(),
        ("take", measured.LONG_LIST if take is None else take),
    ])


def ranking_request(
    conditions: Mapping[str, Any], member_entity_ids: Sequence[str], long_list_ids: Sequence[str]
) -> Request:
    """One member's own ranking of the long list. It differs from the group search in its signal and in the
    set to rank, so a difference between two members' orders can only come from their favourites."""
    return _checked("/v2/insights", [
        ("filter.type", PLACE),
        ("signal.interests.entities", list(member_entity_ids)),
        ("filter.results.entities", list(long_list_ids)),
        *_condition_pairs(conditions),
        *_explain_pairs(),
        ("take", len(long_list_ids)),
    ])


def add_param(request: Request, name: str, value: Any) -> Request:
    """The same request with one more parameter, checked against the allowlist again."""
    return _checked(request.path, [*request.params, (name, value)])


def unsupported_type_request() -> Request:
    """The probe's one deliberate bad request, to see the error Qloo sends for a type it does not support."""
    return Request("/v2/insights", (("filter.type", "urn:entity:destination"), ("take", "1")))
