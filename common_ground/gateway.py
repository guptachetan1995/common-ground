"""The one way in: every tool call and every click reaches `Gateway.dispatch(tool, args, actor)`.

The page's buttons, the member page, the agent console, the agent address, the command line and the MCP
front end all call it, so there is no second code path. Before a handler runs it settles who is calling,
whether that caller may run this name at all, and whether the arguments are exactly the ones declared;
a refusal has a name and is written to the workspace's activity log with the caller, never the arguments.

The registry of tools (agent_tools.TOOLS) and the human-only verbs (person_verbs.VERBS) are two separate
dictionaries. A verb that is not a tool is looked up only for a person, so an agent that asks for one
gets `not_a_tool` whether or not it knows the name.
"""
from __future__ import annotations

import dataclasses
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from . import agent_tools, outings, person_verbs, settings, wire
from .refusal import Refusal

AGENT = "agent"
PERSON = "person"
MAX_TOOL_NAME = 64
MAX_KEY_SHOWN = 40
ID_LISTS = ("signal.interests.entities", "filter.exclude.entities", "filter.results.entities")
IDS_SHOWN = 6

_JSON_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


@dataclass(frozen=True)
class Actor:
    """Who is calling. A member's own link names the outing and member it belongs to."""

    kind: str
    workspace: str
    outing: str | None = None
    member: str | None = None

    @classmethod
    def agent(cls, workspace: str) -> "Actor":
        return cls(AGENT, workspace)

    @classmethod
    def organiser(cls, workspace: str) -> "Actor":
        return cls(PERSON, workspace)

    @classmethod
    def member_link(cls, workspace: str, outing: str, member: str) -> "Actor":
        return cls(PERSON, workspace, outing, member)

    @property
    def is_member(self) -> bool:
        return self.member is not None

    @property
    def role(self) -> str | None:
        if self.kind == AGENT:
            return None
        return f"member:{self.member}" if self.is_member else "organiser"


def shown_params(request) -> dict[str, str]:
    """A request's parameters as the trace shows them. Long lists of ids are counted, not printed."""
    shown = {}
    for name, value in request.as_dict().items():
        count = value.count(",") + 1
        shown[name] = f"<{count} ids>" if name in ID_LISTS and count > IDS_SHOWN else value
    return shown


class Spend:
    """What one tool call spends on one outing, and the trace lines it leaves.

    It is the meter a source consults: `admit` refuses the next request when the outing's limit, or the
    agent's allowance for an agent-started call, is used up; `record` writes the ledger row and counts the
    request. On exit it writes the spend and the trace to the outing in one change, whatever happened inside,
    together with anything registered through `also`. The server's daily ceiling is the live source's own."""

    def __init__(self, ctx: "Context", out: Mapping, tool: str, *, max_calls: int | None, trace_actor: str):
        self._ctx = ctx
        self._outing_id = out["id"]
        self._tool = tool
        self._trace_actor = trace_actor
        self._first_step = len(out["trace"]) + 1
        self._started_with = out["budget"]["spent"]
        self._source = ctx.gateway.source_for(out)
        self._also: list[Callable[[dict], None]] = []
        self._last: tuple[str, int] | None = None
        self.spent = out["budget"]["spent"]
        self.limit = out["budget"]["limit"] if max_calls is None else min(out["budget"]["limit"], max_calls)
        self.entries: list[dict] = []

    @property
    def calls_this_run(self) -> int:
        return self.spent - self._started_with

    def admit(self, live: bool) -> None:
        if self.spent >= self.limit:
            raise Refusal("over_limit", f"{self.spent} of {self.limit}")
        if live and self._ctx.actor.kind == AGENT:
            ws = outings.workspace(self._ctx.doc, self._ctx.actor.workspace)
            used = outings.agent_calls_24h(ws, self._ctx.now())
            allowed = self._ctx.config.agent_calls_per_day
            if used >= allowed:
                raise Refusal("agent_allowance_spent", f"{used} of {allowed}")

    def record(self, path: str, cache: str, ms: int, live: bool) -> None:
        self._last = (cache, ms)
        costs = cache != "cache"
        if costs:
            self.spent += 1
        ws, now, started_by = self._ctx.actor.workspace, self._ctx.now(), self._ctx.actor.kind
        self._ctx.commit(lambda doc: outings.log_call(
            doc, path=path, cache=cache, ms=ms, started_by=started_by,
            workspace_id=outings.ledger_label(ws), now=now,
        ))
        if live and costs and started_by == AGENT:
            self._ctx.commit(lambda doc: outings.record_agent_call(doc, ws, now))

    def _add(self, because: str, member: str | None, request, outcome: str) -> None:
        cache, ms = self._last if request is not None and self._last else (None, None)
        self.entries.append({
            "step": self._first_step + len(self.entries),
            "tool": self._tool,
            "actor": self._trace_actor,
            "member": member,
            "because": because,
            "request": None if request is None else {"path": request.path, "params": shown_params(request)},
            "cache": cache,
            "ms": ms,
            "callsSpent": self.spent,
            "outcome": outcome,
        })

    def call(self, request, because: str, *, member: str | None = None, read: Callable | None = None) -> Any:
        """One request through the source, with its trace line. `read` turns the body into records."""
        self._last = None
        try:
            reply = self._source.fetch(request, self)
            parsed = reply.body if read is None else read(reply.body)
        except Refusal as error:
            self._add(because, member, request if self._last else None, error.code)
            raise
        self._add(because, member, request, "ok")
        return parsed

    def note(self, because: str, *, member: str | None = None, outcome: str = "ok") -> None:
        """A trace line for a skip or a stop: no request was made."""
        self._add(because, member, None, outcome)

    def also(self, change: Callable[[dict], None]) -> None:
        self._also.append(change)

    def __enter__(self) -> "Spend":
        return self

    def __exit__(self, *exc) -> None:
        if not (self.entries or self._also or self.spent != self._started_with):
            return

        def change(out: dict) -> None:
            out["budget"]["spent"] = self.spent
            out["trace"].extend(self.entries)
            for apply in self._also:
                apply(out)

        ws = self._ctx.actor.workspace
        self._ctx.commit(lambda doc: outings.update_outing(doc, ws, self._outing_id, change))


class Context:
    """What a handler may use: the latest document, the source, the limits and the means to change them."""

    def __init__(self, gateway: "Gateway", actor: Actor) -> None:
        self.gateway = gateway
        self.actor = actor

    @property
    def doc(self) -> dict:
        return self.gateway.document

    @property
    def config(self) -> settings.Settings:
        return self.gateway.config

    def now(self) -> float:
        return self.gateway.clock()

    def token(self) -> str:
        return self.gateway.token()

    def commit(self, change: Callable[[dict], dict]) -> None:
        self.gateway.commit(change)

    def outing(self, outing_id: str) -> dict:
        if self.actor.is_member and outing_id != self.actor.outing:
            raise Refusal("wrong_member", "this link belongs to another outing")
        return outings.outing(self.doc, self.actor.workspace, outing_id)

    def update(self, outing_id: str, change: Callable[[dict], None], *, stale: bool = False) -> None:
        ws = self.actor.workspace
        self.commit(lambda doc: outings.update_outing(doc, ws, outing_id, change, stale=stale))

    def spending(
        self, out: Mapping, tool: str, *, max_calls: int | None = None, trace_actor: str | None = None
    ) -> Spend:
        return Spend(self, out, tool, max_calls=max_calls, trace_actor=trace_actor or self.actor.kind)


class Gateway:
    """The document, the source and the clock, behind `dispatch`. It never holds the key."""

    def __init__(
        self,
        source,
        config: settings.Settings,
        *,
        sample=None,
        clock: Callable[[], float] = time.time,
        token: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        self.source = source
        self.sample = sample if source.live else None
        self.config = dataclasses.replace(config, api_key=None)
        self.key_status = config.key_status
        self.clock = clock
        self.token = token
        self._doc = outings.new_doc()
        self._doc_lock = threading.Lock()
        self._workspace_locks: dict[str, threading.Lock] = {}

    def __repr__(self) -> str:
        return f"Gateway(source: {self.source.name}, key: {self.key_status})"

    @property
    def document(self) -> dict:
        return self._doc

    def new_outing_source(self) -> str:
        """The kind of data a new outing is answered from, fixed when it opens. An outing opens on invented
        sample data only when the gateway holds a sample source and the live source is spent for today."""
        if not self.source.live:
            return outings.SYNTHETIC
        return outings.SYNTHETIC if self.sample is not None and self.source.exhausted() else outings.LIVE

    def source_for(self, out: dict):
        """The source an outing's calls go to: the one it was opened on, whatever has happened since."""
        if out["source"] == outings.SYNTHETIC and self.sample is not None:
            return self.sample
        return self.source

    def commit(self, change: Callable[[dict], dict]) -> None:
        with self._doc_lock:
            self._doc = change(self._doc)

    def new_workspace(self) -> str:
        made: list[str] = []

        def add(doc: dict) -> dict:
            doc, ws_id = outings.add_workspace(doc, token=self.token, now=self.clock())
            made.append(ws_id)
            return outings.forget_least_recent(doc)

        self.commit(add)
        return made[0]

    def _lock_for(self, ws_id: str) -> threading.Lock:
        with self._doc_lock:
            return self._workspace_locks.setdefault(ws_id, threading.Lock())

    def dispatch(self, tool: Any, args: Any, actor: Actor) -> dict:
        """Run one tool or verb as `actor`. Answers `{ok, outcome, result}`, or `{ok, outcome, error}`."""
        if not isinstance(actor, Actor) or actor.kind not in (AGENT, PERSON):
            return _failure(Refusal("unknown_actor"))
        try:
            outings.workspace(self._doc, actor.workspace)
        except Refusal as error:
            return _failure(error)
        name = tool if isinstance(tool, str) else ""
        ws = actor.workspace
        with self._lock_for(ws):
            now = self.clock()
            self.commit(lambda doc: outings.touch(doc, ws, now))
            try:
                result = self._run(name, args, Context(self, actor))
                answer = {"ok": True, "outcome": "ok", "result": result}
            except Refusal as error:
                answer = _failure(error)
            self.commit(lambda doc: outings.log_activity(
                doc, ws, actor=actor.kind, as_=actor.role, tool=name[:MAX_TOOL_NAME],
                outcome=answer["outcome"], now=now,
            ))
            return answer

    def _run(self, name: str, args: Any, ctx: Context) -> Any:
        actor = ctx.actor
        tool = agent_tools.TOOLS.get(name)
        verb = person_verbs.VERBS.get(name)
        if len(name) > MAX_TOOL_NAME or (tool is None and verb is None):
            raise Refusal("not_a_tool")
        if actor.kind == AGENT:
            if tool is None:
                raise Refusal("not_a_tool")
        elif actor.is_member and not (verb is not None and verb.members):
            raise Refusal("wrong_actor", "a member's own link runs only resolve_match and add_own_favourite")
        spec = tool if tool is not None else verb
        return spec.run(ctx, **_arguments(args, spec.args))


def _failure(error: Refusal) -> dict:
    detail: dict[str, Any] = {"code": error.code, "detail": error.detail}
    if isinstance(error, wire.QlooError):
        detail["status"] = error.status
    return {"ok": False, "outcome": error.code, "error": detail}


def _arguments(args: Any, spec: agent_tools.Args) -> dict:
    """The arguments exactly as declared: nothing extra, everything required, each of the declared type."""
    args = {} if args is None else args
    if not isinstance(args, dict):
        raise Refusal(outings.BAD_ARGUMENTS, "arguments")
    for key in args:
        if key not in spec.declared:
            raise Refusal("smuggled_field", str(key)[:MAX_KEY_SHOWN])
    for key in spec.required:
        if key not in args:
            raise Refusal(outings.BAD_ARGUMENTS, key)
    for key, value in args.items():
        kinds = spec.declared[key]["type"]
        kinds = (kinds,) if isinstance(kinds, str) else kinds
        if not any(_JSON_TYPES[kind](value) for kind in kinds):
            raise Refusal(outings.BAD_ARGUMENTS, key)
    return args
