"""Where Qloo's JSON comes from.

FakeSource answers in Qloo's documented shapes from invented data. Every place, candidate and tag in it is
made up, with ids in the reserved range 00000000-0000-4000-8000-… (places start with 0, candidates with c),
so nothing there is Qloo data and nothing leaves the process. `respond` takes a bare path and parameter
pairs so a test can serve it over a loopback socket.

LiveSource asks Qloo. It owns the private cache, the day's call count and the bounded retry, and it is
the only place the key is held after start-up; the key goes to wire.send and nowhere else. Both sources
take an optional `meter` (the caller's view of the outing's limit and allowance): the source asks it
before each request that costs a call and tells it afterwards, so a refusal stops the next request
rather than being noticed after it.
"""
from __future__ import annotations

import collections
import hashlib
import threading
import time
from typing import Callable, Mapping, Sequence

from . import measured, qloo_calls, records, settings, wire
from .refusal import Refusal

RESERVED = "00000000-0000-4000-8000-"
SYNTHETIC_NOTE = "Synthetic sample data, not from Qloo"
SYNTHETIC = "synthetic"
RETRY_WAITS = (1.0, 3.0)
CACHE_ENTRIES = 256
NO_KEY = "no_key"
DAILY_CEILING_SPENT = "daily_ceiling_spent"

CITIES = (("New York City", 200), ("Los Angeles", 120))
_FIRST = (
    "Alder", "Brindle", "Cobble", "Dunmore", "Ember", "Fallow", "Garnet", "Hollis", "Ivory", "Juniper",
    "Kestrel", "Linden", "Marlow", "Nettle", "Orchard", "Pemberton", "Quill", "Rowan", "Sorrel", "Tansy",
)
_SECOND = (
    "Table", "Kitchen", "Larder", "Supper Club", "Cantina", "Bistro", "Taproom", "Canteen", "Room", "House",
)
_STREETS = ("Alder", "Bay", "Cedar", "Dock", "Elm", "Fern", "Grove", "Hill", "Inlet", "Jetty")
_PRICES = (1, 2, 3, 4, 2, 3)
_KINDS = ("restaurant", "restaurant", "bar", "restaurant", "cafe", "restaurant", "restaurant")
_CUISINES = ("italian", "thai", "japanese", "mexican", "indian", "french", "greek", "ethiopian")

# The sample group's favourites come up first as what they are, so the sample demo's first match reads
# right. Any other name keeps the arbitrary hashed order, and a person still says which match they meant.
SAMPLE_TYPES = {
    "lost in translation": "urn:entity:movie",
    "jiro dreams of sushi": "urn:entity:movie",
    "khruangbin": "urn:entity:artist",
    "radiohead": "urn:entity:artist",
    "the bear": "urn:entity:tv_show",
    "dune": "urn:entity:book",
    "patagonia": "urn:entity:brand",
    "katz's delicatessen": "urn:entity:place",
}

TAGS = {
    slug: {"id": f"urn:tag:synthetic:{slug}", "name": name, "type": "urn:tag:synthetic:" + group}
    for slug, name, group in (
        ("restaurant", "Restaurant", "kind"),
        ("fast_food", "Fast Food Restaurant", "kind"),
        ("bar", "Bar", "kind"),
        ("cafe", "Cafe", "kind"),
        *((c, c.capitalize(), "cuisine") for c in _CUISINES),
    )
}


def _catalog() -> list[dict]:
    places = []
    for city, count in CITIES:
        for i in range(count):
            j = len(places)
            name = f"{_FIRST[i % len(_FIRST)]} {_SECOND[i // len(_FIRST) % len(_SECOND)]}"
            places.append({
                "index": j,
                "entity_id": f"{RESERVED}{0x1000 + j:012x}",
                "name": name,
                "city": city,
                "price": _PRICES[i % len(_PRICES)],
                "closed": qloo_calls.WEEKDAYS[i * 3 % 7],
                "kind": _KINDS[i % len(_KINDS)],
                "cuisine": _CUISINES[i % len(_CUISINES)],
                "address": f"{j * 37 % 900 + 10} {_STREETS[j % len(_STREETS)]} St, {city}",
                "website": f"https://example.invalid/{j}" if j % 2 == 0 else None,
            })
    return places


def _split(value: str) -> list[str]:
    return [part for part in value.split(",") if part]


class FakeSource:
    """Invented answers, deterministic for a given request. `tastes` maps a favourite's text (lower case)
    to "forward" or "reverse", which orders the whole catalogue by index or against it, so a test can build
    members whose rankings agree or are opposite."""

    name = "fake"
    live = False

    def __init__(
        self,
        *,
        tastes: Mapping[str, str] | None = None,
        with_affinity: bool = True,
        with_explainability: bool = True,
    ) -> None:
        self._tastes = dict(tastes or {})
        self._with_affinity = with_affinity
        self._with_explainability = with_explainability
        self._places = _catalog()
        self._text_of: dict[str, str] = {}
        self._orders: dict[str, list[int]] = {}

    def fetch(self, request: qloo_calls.Request, meter=None) -> wire.Reply:
        if meter:
            meter.admit(live=False)
        status, body = self.respond(request.path, request.params)
        if meter:
            meter.record(request.path, SYNTHETIC, 0, live=False)
        if status != 200:
            raise wire.QlooError(wire.outcome_for(status), status, records.skeleton(body))
        return wire.Reply(status, body, 0)

    def report(self) -> dict:
        return {"source": self.name, "liveCallsToday": 0, "cacheHits": 0}

    def exhausted(self) -> bool:
        return False

    def respond(self, path: str, params: Sequence[tuple[str, str]]) -> tuple[int, dict]:
        values = dict(params)
        if path == "/search":
            return 200, self._search(values, [t for name, v in params if name == "types" for t in _split(v)])
        if path == "/v2/tags":
            return 200, self._tags(values)
        if path == "/v2/insights":
            if values.get("filter.type") != qloo_calls.PLACE:
                return 403, {"success": False, "error": {"code": 403, "message": "unsupported filter.type"}}
            return 200, self._insights(values)
        return 404, {"success": False, "error": {"code": 404, "message": "no such route"}}

    def candidate_type_order(self, text: str, types: Sequence[str]) -> list[str]:
        known = SAMPLE_TYPES.get(text.lower())
        if known in types:
            return [known, *(t for t in types if t != known)]
        turn = int(hashlib.sha256(text.lower().encode()).hexdigest()[:8], 16) % len(types)
        return list(types[turn:]) + list(types[:turn])

    def _search(self, values: Mapping[str, str], types: Sequence[str]) -> dict:
        text = values["query"]
        wanted = [t for t in types if t != records.PERSON] or list(measured.FAVOURITE_TYPES)
        results = []
        for i, kind in enumerate(self.candidate_type_order(text, wanted)[: int(values.get("take", 5))]):
            digest = hashlib.sha256(f"{text.lower()}|{kind}".encode()).hexdigest()
            entity_id = f"{RESERVED}c{digest[:11]}"
            self._text_of[entity_id] = text.lower()
            results.append({
                "entity_id": entity_id,
                "name": text if i == 0 else f"{text} ({kind.rsplit(':', 1)[-1].replace('_', ' ')})",
                "type": kind,
                "popularity": round(0.9 - 0.1 * i, 2),
                "disambiguation": SYNTHETIC_NOTE,
            })
        return {"results": results}

    def _tags(self, values: Mapping[str, str]) -> dict:
        needle = values.get("filter.query", "").lower()
        found = [t for t in TAGS.values() if needle in t["name"].lower()]
        return {"results": {"tags": found[: int(values.get("take", 10))]}}

    def _order(self, entity_id: str) -> list[int]:
        """Catalogue indexes from this entity's most to least favoured place."""
        if entity_id not in self._orders:
            taste = self._tastes.get(self._text_of.get(entity_id, ""))
            count = len(self._places)
            if taste == "forward":
                order = list(range(count))
            elif taste == "reverse":
                order = list(reversed(range(count)))
            else:
                def seeded(j: int) -> bytes:
                    return hashlib.sha256(f"{entity_id}|{j}".encode()).digest()

                order = sorted(range(count), key=seeded)
            self._orders[entity_id] = order
        return self._orders[entity_id]

    def _score(self, entity_id: str, index: int) -> float:
        return 0.97 - 0.62 * self._order(entity_id).index(index) / (len(self._places) - 1)

    def _mean_score(self, signal: Sequence[str], index: int) -> float:
        return sum(self._score(e, index) for e in signal) / len(signal) if signal else 1.0

    def _average_influence(self, entity_id: str, shown: Sequence[Mapping]) -> float:
        return round(sum(self._score(entity_id, p["index"]) for p in shown) / max(len(shown), 1), 2)

    def keeps(self, place: Mapping, values: Mapping[str, str]) -> bool:
        city = values.get("filter.location.query") or values.get("filter.geocode.name")
        if city and city.lower() not in place["city"].lower() and place["city"].lower() not in city.lower():
            return False
        day = values.get("filter.hours")
        if day and place["closed"] == day:
            return False
        low, high = values.get("filter.price_level.min"), values.get("filter.price_level.max")
        if (low and place["price"] < int(low)) or (high and place["price"] > int(high)):
            return False
        tag = values.get("filter.tags")
        return not tag or tag in (TAGS[place["kind"]]["id"], TAGS[place["cuisine"]]["id"])

    def _insights(self, values: Mapping[str, str]) -> dict:
        signal = _split(values.get("signal.interests.entities", ""))
        excluded = set(_split(values.get("filter.exclude.entities", "")))
        restricted = set(_split(values.get("filter.results.entities", "")))
        kept = [
            p for p in self._places
            if self.keeps(p, values) and p["entity_id"] not in excluded
            and (not restricted or p["entity_id"] in restricted)
        ]
        scored = [(self._mean_score(signal, p["index"]), p) for p in kept]
        scored.sort(key=lambda row: (-row[0], row[1]["index"]))
        scored = scored[: min(int(values.get("take", 20)), 50)]
        explain = values.get("feature.explainability") == "true" and self._with_explainability
        entities = [self._entity(p, score, signal, explain) for score, p in scored]
        query: dict = {}
        if values.get("filter.location.query"):
            query["locality"] = {"signal": 1.0}
        if explain and signal:
            query["explainability"] = {records.INFLUENCE_KEY: [
                {"entity_id": e, "score": self._average_influence(e, [p for _, p in scored])} for e in signal
            ]}
        body = {"success": True, "results": {"entities": entities}}
        if query:
            body["query"] = query
        return body

    def _entity(self, place: Mapping, score: float, signal: Sequence[str], explain: bool) -> dict:
        query: dict = {}
        if self._with_affinity and signal:
            query["affinity"] = round(score, 2)
        if explain and signal:
            query["explainability"] = {records.INFLUENCE_KEY: [
                {"entity_id": e, "score": round(self._score(e, place["index"]), 2)} for e in signal
            ]}
        properties = {"address": place["address"]}
        if place["website"]:
            properties["website"] = place["website"]
        entity = {
            "entity_id": place["entity_id"],
            "name": place["name"],
            "type": qloo_calls.PLACE,
            "subtype": qloo_calls.PLACE,
            "tags": [TAGS[place["kind"]], TAGS[place["cuisine"]]],
            "properties": properties,
        }
        if query:
            entity["query"] = query
        return entity

    @property
    def catalogue(self) -> list[dict]:
        return list(self._places)


class Ledger:
    """Live requests the server has made today (UTC), kept in memory, and how many answers the cache served.

    The count belongs to one run of the server, not to a calendar day: a restart empties it."""

    def __init__(self, ceiling: int, clock: Callable[[], float]) -> None:
        self.ceiling = ceiling
        self.cache_hits = 0
        self._clock = clock
        self._day = ""
        self._used = 0
        self._lock = threading.Lock()

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    def used(self) -> int:
        with self._lock:
            return self._used if self._day == self._today() else 0

    def take(self) -> None:
        """Count one request that is about to be made, or refuse because the day's ceiling is spent."""
        with self._lock:
            today = self._today()
            if self._day != today:
                self._day, self._used = today, 0
            if self._used >= self.ceiling:
                raise Refusal(DAILY_CEILING_SPENT, f"{self._used} of {self.ceiling}")
            self._used += 1

    def hit(self) -> None:
        with self._lock:
            self.cache_hits += 1


def _retryable(error: wire.QlooError) -> bool:
    return error.status == 429 or error.status >= 500


class LiveSource:
    """Qloo's hackathon API behind a private in-memory cache, a day ceiling and a bounded retry.

    Every request first checks that the response shapes have been verified against real responses
    (measured.require_verified), so nothing live runs on a documented guess. An answer comes from the cache
    when the same request was answered within the time to live; that costs nothing and is logged as such.
    A 429 or a 5xx is asked again after one second and again after three; each attempt is a live call."""

    name = "live"
    live = True

    def __init__(
        self,
        key: str,
        *,
        daily_ceiling: int,
        cache_ttl_s: int,
        base_url: str = wire.BASE_URL,
        send: Callable = wire.send,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key = key
        self._base_url = base_url
        self._send = send
        self._clock = clock
        self._sleep = sleep
        self._ttl = cache_ttl_s
        self._cache: collections.OrderedDict[str, tuple[float, wire.Reply]] = collections.OrderedDict()
        self._cache_lock = threading.Lock()
        self.ledger = Ledger(daily_ceiling, clock)

    def __repr__(self) -> str:
        return "LiveSource(key: set)"

    @staticmethod
    def cache_key(request: qloo_calls.Request) -> str:
        """A hash of the path and parameters. The key is never part of a request, so never part of this."""
        return hashlib.sha256((request.path + "?" + request.query_string()).encode()).hexdigest()

    def _cached(self, cache_key: str) -> wire.Reply | None:
        with self._cache_lock:
            found = self._cache.get(cache_key)
            if found is None:
                return None
            if found[0] <= self._clock():
                del self._cache[cache_key]
                return None
            self._cache.move_to_end(cache_key)
            return found[1]

    def _remember(self, cache_key: str, reply: wire.Reply) -> None:
        with self._cache_lock:
            self._cache[cache_key] = (self._clock() + self._ttl, reply)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)

    def fetch(self, request: qloo_calls.Request, meter=None) -> wire.Reply:
        measured.require_verified()
        cache_key = self.cache_key(request)
        cached = self._cached(cache_key)
        if cached is not None:
            self.ledger.hit()
            if meter:
                meter.record(request.path, "cache", 0, live=False)
            return wire.Reply(cached.status, cached.body, 0)
        waits = iter(RETRY_WAITS)
        while True:
            if meter:
                meter.admit(live=True)
            self.ledger.take()
            started = time.monotonic()
            try:
                reply = self._send(request, self._key, base_url=self._base_url)
            except Refusal as error:
                if meter:
                    meter.record(request.path, "miss", int((time.monotonic() - started) * 1000), live=True)
                wait = next(waits, None)
                if wait is None or not (isinstance(error, wire.QlooError) and _retryable(error)):
                    raise
                self._sleep(wait)
                continue
            if meter:
                meter.record(request.path, "miss", reply.ms, live=True)
            self._remember(cache_key, reply)
            return reply

    def exhausted(self) -> bool:
        return self.ledger.used() >= self.ledger.ceiling

    def report(self) -> dict:
        return {
            "source": self.name,
            "liveCallsToday": self.ledger.used(),
            "dailyCeiling": self.ledger.ceiling,
            "cacheHits": self.ledger.cache_hits,
            "cacheEntries": len(self._cache),
        }


def make(
    config: settings.Settings,
    *,
    base_url: str = wire.BASE_URL,
    send: Callable = wire.send,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> FakeSource | LiveSource:
    """The source the settings ask for. Live without a key is refused, never answered with sample data."""
    if config.provider == "fake":
        return FakeSource()
    if not config.api_key:
        raise Refusal(NO_KEY, "key: missing")
    return LiveSource(
        config.api_key,
        daily_ceiling=config.daily_live_calls,
        cache_ttl_s=config.cache_ttl_s,
        base_url=base_url,
        send=send,
        clock=clock,
        sleep=sleep,
    )
