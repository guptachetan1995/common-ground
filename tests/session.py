"""Shared scaffolding for tests that go through the gateway: a session on a fake or stubbed live source,
a scripted source whose rankings a test controls, and a stand-in for the network."""
import copy
from unittest import mock

from common_ground import measured, outings, settings, sources, wire
from common_ground.gateway import Actor, Gateway
from tests.support import fake_key
from tests.test_outings import sample_args


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)


class Transport:
    """Stands in for wire.send: scripted failures first, then answers from a source; keeps what it saw."""

    def __init__(self, source=None, failures=(), fail_when=None):
        self.failures = list(failures)
        self.fail_when = fail_when
        self.source = source or sources.FakeSource()
        self.seen = []

    def __call__(self, request, key, base_url=wire.BASE_URL):
        self.seen.append((request, key, base_url))
        status = None
        if self.failures:
            status = self.failures.pop(0)
        elif self.fail_when and self.fail_when(request):
            status = 503
        if status:
            raise wire.QlooError(wire.outcome_for(status), status, {})
        return self.source.fetch(request)


def verified():
    return mock.patch.object(measured, "UNVERIFIED", frozenset())


def split(value):
    return [part for part in value.split(",") if part]


def two_level(rank, size):
    """Affinities with a wide gap at the half-way line, so no tie tolerance blurs who is inside."""
    half = (size + 1) // 2
    return round(0.95 - 0.005 * (rank - 1), 3) if rank <= half else round(0.55 - 0.005 * (rank - half - 1), 3)


class ScriptedSource(sources.FakeSource):
    """A fake whose personal rankings a test dictates. `script` maps a favourite's text (lower case) to a
    function that takes the long list's ids and returns the ids Qloo would return, in that person's order."""

    def __init__(self, script, group_size=None, **options):
        super().__init__(**options)
        self.script = script
        self.group_size = group_size

    def _insights(self, values):
        asked = split(values.get("filter.results.entities", ""))
        if not asked:
            body = super()._insights(values)
            if self.group_size is not None:
                body["results"]["entities"] = body["results"]["entities"][: self.group_size]
            return body
        signal = split(values["signal.interests.entities"])
        ordered = self.script[self._text_of[signal[0]]](asked)
        entities = []
        for rank, entity_id in enumerate(ordered, 1):
            query = {"affinity": two_level(rank, len(ordered))}
            if self._with_explainability:
                query["explainability"] = {
                    "signal.interests.entities": [{"entity_id": e, "score": 0.5} for e in signal]
                }
            entities.append(
                {"entity_id": entity_id, "name": "ranked", "type": "urn:entity:place", "query": query}
            )
        return {"success": True, "results": {"entities": entities}}


def forward(ids):
    return list(ids)


def reverse(ids):
    return list(reversed(ids))


def first(n):
    return lambda ids: list(ids)[:n]


def slice_of(k, n):
    return lambda ids: list(ids)[k * n:(k + 1) * n]


class Session:
    """A workspace on a gateway, with the sample group's walk broken into steps a test can mix and match."""

    def __init__(self, source=None, clock=None, sample=None, **config):
        self.clock = clock or Clock()
        self.config = settings.Settings(**{"provider": "fake", **config})
        self.source = source or sources.FakeSource()
        self.gateway = Gateway(self.source, self.config, sample=sample, clock=self.clock)
        self.ws = self.gateway.new_workspace()
        self.agent = Actor.agent(self.ws)
        self.organiser = Actor.organiser(self.ws)

    def run(self, tool, args=None, actor=None):
        return self.gateway.dispatch(tool, args, actor or self.agent)

    def ok(self, tool, args=None, actor=None):
        answer = self.run(tool, args, actor)
        assert answer["ok"], answer
        return answer["result"]

    def code(self, tool, args=None, actor=None):
        answer = self.run(tool, args, actor)
        assert not answer["ok"], answer
        return answer["outcome"]

    def member_link(self, outing_id, member_id):
        return Actor.member_link(self.ws, outing_id, member_id)

    def open(self, args=None, actor=None):
        return self.ok("open_outing", {**sample_args(), **(args or {})}, actor)["outingId"]

    def outing(self, outing_id="out_001"):
        return copy.deepcopy(outings.outing(self.gateway.document, self.ws, outing_id))

    def search_all(self, outing_id="out_001", actor=None):
        for member in self.outing(outing_id)["members"]:
            for favourite in member["favourites"]:
                self.ok("look_up_favourite", {
                    "outing_id": outing_id, "member_id": member["id"], "favourite_id": favourite["id"],
                }, actor)

    def resolve_all(self, outing_id="out_001", which=0):
        for member in self.outing(outing_id)["members"]:
            for favourite in member["favourites"]:
                self.ok("resolve_match", {
                    "outing_id": outing_id, "member_id": member["id"], "favourite_id": favourite["id"],
                    "entity_id": favourite["candidates"][which]["entityId"],
                }, self.organiser)

    def choose_kind(self, outing_id="out_001", word="restaurant", actor=None):
        tags = self.ok("look_up_kind", {"outing_id": outing_id, "query": word}, actor)["tags"]
        self.ok("change_conditions", {"outing_id": outing_id, "kind_tag": tags[0]["id"]}, self.organiser)

    def ready(self, args=None, kind=True, actor=None):
        outing_id = self.open(args, actor)
        self.search_all(outing_id, actor)
        self.resolve_all(outing_id)
        if kind:
            self.choose_kind(outing_id, actor=actor)
        return outing_id

    def compare(self, outing_id="out_001", actor=None, **args):
        return self.ok("run_comparison", {"outing_id": outing_id, **args}, actor)


def live_session(transport, key=None, ceiling=1000, sample=None, **config):
    """A session on a LiveSource whose network is `transport`. The caller wraps its use in `verified()`."""
    key = key or fake_key()
    clock = Clock()
    source = sources.LiveSource(
        key, daily_ceiling=ceiling, cache_ttl_s=3600, send=transport, clock=clock, sleep=clock.sleep
    )
    return Session(source, clock=clock, sample=sample, provider="live", api_key=key, **config)
