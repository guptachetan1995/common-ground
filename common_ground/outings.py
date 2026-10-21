"""Workspaces and outings as pure functions over one JSON document.

Every function takes the document and returns a new one; nothing it is given is changed, so a reader
holding an older document always sees a consistent snapshot. Time and randomness come in as arguments.
Functions that look something up return the document's own dicts, which callers must not change.
Who may call a function is not decided here.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import Any, Callable, Mapping, Sequence

from . import fair_share, qloo_calls, records
from .refusal import Refusal

BAD_ARGUMENTS = "bad_arguments"
MAX_LABEL = 60
MAX_NAME = 24
MAX_FAVOURITE = 60
MAX_PLACE_TEXT = 60
MAX_WHEN = 40
MAX_RADIUS_M = 50000
MAX_WORKSPACES = 200
MAX_LOGGED_CALLS = 5000
MAX_LOGGED_ACTIVITY = 1000
DAY_SECONDS = 86400
RESOLVERS = ("member", "organiser_for")
LIVE = "live"
SYNTHETIC = "synthetic"
SOURCES = (LIVE, SYNTHETIC)
CHANGEABLE = ("day", "price_min", "price_max", "place_text", "radius_m", "kind_tag")


def new_doc() -> dict:
    return {"workspaces": [], "calls": []}


def iso(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise Refusal(BAD_ARGUMENTS, name)
    text = " ".join(value.split())
    if not text or len(text) > limit:
        raise Refusal(BAD_ARGUMENTS, name)
    return text


def whole(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refusal(BAD_ARGUMENTS, name)
    return value


def _conditions(place_text: Any, day: Any, price_min: Any, price_max: Any, radius_m: Any) -> dict:
    if day not in qloo_calls.WEEKDAYS:
        raise Refusal(BAD_ARGUMENTS, "day")
    low = None if price_min is None else whole(price_min, "price_min", 1, 4)
    high = None if price_max is None else whole(price_max, "price_max", 1, 4)
    if low is not None and high is not None and low > high:
        raise Refusal(BAD_ARGUMENTS, "price_min")
    return {
        "placeText": text(place_text, "place_text", MAX_PLACE_TEXT),
        "day": day,
        "priceMin": low,
        "priceMax": high,
        "radiusM": None if radius_m is None else whole(radius_m, "radius_m", 0, MAX_RADIUS_M),
    }


def scenario_args(data: Mapping[str, Any]) -> dict:
    """A scenario file (favourites carry a domain label) as the arguments `open_outing` takes."""
    members = [
        {"name": m["name"], "favourites": [f["name"] for f in m["favourites"]]} for m in data["members"]
    ]
    return {**{k: v for k, v in data.items() if k != "members"}, "members": members}


def _with_workspace(doc: dict, ws_id: str, change: Callable[[dict], None]) -> dict:
    spaces = []
    found = False
    for ws in doc["workspaces"]:
        if ws["id"] == ws_id:
            found = True
            ws = {**ws, "outings": list(ws["outings"])}
            change(ws)
        spaces.append(ws)
    if not found:
        raise Refusal("no_workspace")
    return {**doc, "workspaces": spaces}


def add_workspace(doc: dict, *, token: Callable[[], str], now: float) -> tuple[dict, str]:
    ws = {
        "id": "ws_" + token(),
        "agentToken": token(),
        "agentCalls": [],
        "createdAt": iso(now),
        "lastSeenAt": iso(now),
        "outings": [],
        "activityLog": [],
    }
    return {**doc, "workspaces": [*doc["workspaces"], ws]}, ws["id"]


def workspace(doc: dict, ws_id: str) -> dict:
    for ws in doc["workspaces"]:
        if ws["id"] == ws_id:
            return ws
    raise Refusal("no_workspace")


def find_by_agent_token(doc: dict, agent_token: str) -> dict | None:
    return next((ws for ws in doc["workspaces"] if ws["agentToken"] == agent_token), None)


def find_by_member_token(doc: dict, member_token: str) -> tuple[str, str, str] | None:
    for ws in doc["workspaces"]:
        for out in ws["outings"]:
            for m in out["members"]:
                if m["token"] == member_token:
                    return ws["id"], out["id"], m["id"]
    return None


def touch(doc: dict, ws_id: str, now: float) -> dict:
    return _with_workspace(doc, ws_id, lambda ws: ws.update(lastSeenAt=iso(now)))


def forget_least_recent(doc: dict, cap: int = MAX_WORKSPACES) -> dict:
    if len(doc["workspaces"]) <= cap:
        return doc
    keep = sorted(doc["workspaces"], key=lambda ws: ws["lastSeenAt"], reverse=True)[:cap]
    kept_ids = {ws["id"] for ws in keep}
    return {**doc, "workspaces": [ws for ws in doc["workspaces"] if ws["id"] in kept_ids]}


def agent_calls_24h(ws: Mapping, now: float) -> int:
    return sum(1 for t in ws["agentCalls"] if now - t < DAY_SECONDS)


def record_agent_call(doc: dict, ws_id: str, now: float) -> dict:
    def change(ws: dict) -> None:
        ws["agentCalls"] = [t for t in ws["agentCalls"] if now - t < DAY_SECONDS] + [now]

    return _with_workspace(doc, ws_id, change)


def open_outing(
    doc: dict,
    ws_id: str,
    args: Mapping[str, Any],
    *,
    token: Callable[[], str],
    now: float,
    call_limit: int = fair_share.CALL_LIMIT_DEFAULT,
    source: str = SYNTHETIC,
) -> tuple[dict, str]:
    """Validate the `open_outing` arguments and add the outing. The first member is the organiser.
    `source` is the kind of data every call for this outing is answered from, fixed for its whole life."""
    if source not in SOURCES:
        raise Refusal(BAD_ARGUMENTS, "source")
    raw_members = args.get("members")
    if not isinstance(raw_members, list) or not 2 <= len(raw_members) <= fair_share.MAX_MEMBERS:
        raise Refusal(BAD_ARGUMENTS, "members")
    members, names, counter = [], set(), 0
    for i, raw in enumerate(raw_members, 1):
        if not isinstance(raw, Mapping):
            raise Refusal(BAD_ARGUMENTS, "members")
        name = text(raw.get("name"), "members.name", MAX_NAME)
        if name.lower() in names:
            raise Refusal(BAD_ARGUMENTS, "members.name")
        names.add(name.lower())
        typed = raw.get("favourites", [])
        if not isinstance(typed, list):
            raise Refusal(BAD_ARGUMENTS, "members.favourites")
        if len(typed) > fair_share.MAX_FAVOURITES:
            raise Refusal("too_many_favourites")
        favourites = []
        for raw_name in typed:
            counter += 1
            typed_name = text(raw_name, "members.favourites", MAX_FAVOURITE)
            favourites.append(_new_favourite(f"f{counter}", typed_name, "member"))
        members.append({"id": f"m{i}", "name": name, "token": token(), "favourites": favourites})

    kind_query = args.get("kind_query")
    when = args.get("when")
    outing_id = f"out_{len(workspace(doc, ws_id)['outings']) + 1:03d}"
    fresh = {
        "id": outing_id,
        "source": source,
        "label": text(args.get("label"), "label", MAX_LABEL),
        "when": None if when is None else text(when, "when", MAX_WHEN),
        "kindQuery": None if kind_query is None else text(kind_query, "kind_query", MAX_FAVOURITE),
        "conditions": {
            **_conditions(
                args.get("place_text"),
                args.get("day"),
                args.get("price_min"),
                args.get("price_max"),
                args.get("radius_m"),
            ),
            "kindTag": None,
            "setBy": "organiser",
        },
        "members": members,
        "knownTags": [],
        "budget": {"limit": call_limit, "spent": 0, "saved": 0, "stoppedBecause": None},
        "longList": None,
        "places": [],
        "comparison": None,
        "chosen": None,
        "drafts": [],
        "trace": [],
        "revision": 1,
    }
    return _with_workspace(doc, ws_id, lambda ws: ws["outings"].append(fresh)), outing_id


def _new_favourite(fav_id: str, name: str, named_by: str) -> dict:
    return {
        "id": fav_id,
        "name": name,
        "namedBy": named_by,
        "searched": False,
        "candidates": [],
        "resolved": None,
        "resolvedBy": None,
    }


def outing(doc: dict, ws_id: str, outing_id: str) -> dict:
    for out in workspace(doc, ws_id)["outings"]:
        if out["id"] == outing_id:
            return out
    raise Refusal("unknown_outing")


def member(out: Mapping, member_id: str) -> dict:
    for m in out["members"]:
        if m["id"] == member_id:
            return m
    raise Refusal("unknown_member")


def favourite(m: Mapping, favourite_id: str) -> dict:
    for f in m["favourites"]:
        if f["id"] == favourite_id:
            return f
    raise Refusal("unknown_favourite")


def update_outing(
    doc: dict, ws_id: str, outing_id: str, change: Callable[[dict], None], *, stale: bool = False
) -> dict:
    """Apply `change` to a copy of the outing and bump its revision; `stale` marks a comparison stale."""

    def apply(ws: dict) -> None:
        for i, out in enumerate(ws["outings"]):
            if out["id"] == outing_id:
                out = copy.deepcopy(out)
                change(out)
                out["revision"] += 1
                if stale and out["comparison"]:
                    out["comparison"]["stale"] = True
                ws["outings"][i] = out
                return
        raise Refusal("unknown_outing")

    return _with_workspace(doc, ws_id, apply)


def store_candidates(
    doc: dict,
    ws_id: str,
    outing_id: str,
    member_id: str,
    favourite_id: str,
    found: Sequence[records.Candidate],
) -> dict:
    """What one search returned for one favourite, an empty list included. A new search clears any earlier
    resolution."""
    docs = [
        {
            "entityId": c.entity_id, "name": c.name, "type": c.type,
            "popularity": c.popularity, "disambiguation": c.disambiguation,
        }
        for c in found
    ]

    def change(out: dict) -> None:
        fav = favourite(member(out, member_id), favourite_id)
        fav["searched"] = True
        fav["candidates"] = docs
        fav["resolved"] = None
        fav["resolvedBy"] = None

    return update_outing(doc, ws_id, outing_id, change, stale=True)


def resolve(
    doc: dict, ws_id: str, outing_id: str, member_id: str, favourite_id: str, entity_id: str, resolved_by: str
) -> dict:
    """Record which candidate a favourite meant. It must be one this favourite's own search returned."""
    if resolved_by not in RESOLVERS:
        raise Refusal(BAD_ARGUMENTS, "resolved_by")

    def change(out: dict) -> None:
        fav = favourite(member(out, member_id), favourite_id)
        if entity_id not in [c["entityId"] for c in fav["candidates"]]:
            raise Refusal("unknown_entity")
        fav["resolved"] = entity_id
        fav["resolvedBy"] = resolved_by

    return update_outing(doc, ws_id, outing_id, change, stale=True)


def add_favourite(doc: dict, ws_id: str, outing_id: str, member_id: str, name: str, named_by: str) -> dict:
    if named_by not in RESOLVERS:
        raise Refusal(BAD_ARGUMENTS, "named_by")
    typed = text(name, "name", MAX_FAVOURITE)

    def change(out: dict) -> None:
        m = member(out, member_id)
        if len(m["favourites"]) >= fair_share.MAX_FAVOURITES:
            raise Refusal("too_many_favourites")
        taken = [int(f["id"][1:]) for other in out["members"] for f in other["favourites"]]
        m["favourites"].append(_new_favourite(f"f{max(taken, default=0) + 1}", typed, named_by))

    return update_outing(doc, ws_id, outing_id, change)


def store_known_tags(doc: dict, ws_id: str, outing_id: str, tags: Sequence[records.Tag]) -> dict:
    docs = [{"id": t.id, "name": t.name, "type": t.type} for t in tags]
    return update_outing(doc, ws_id, outing_id, lambda out: out.update(knownTags=docs))


def set_conditions(doc: dict, ws_id: str, outing_id: str, changes: Mapping[str, Any]) -> dict:
    """Change conditions after the outing opened. A key that is present is set (None clears a price, the
    radius or the kind); one that is absent stays. The kind must be a tag Qloo returned for this outing."""
    if not changes or set(changes) - set(CHANGEABLE):
        raise Refusal(BAD_ARGUMENTS, "changes")

    def change(out: dict) -> None:
        current = out["conditions"]
        merged = _conditions(
            changes.get("place_text", current["placeText"]),
            changes.get("day", current["day"]),
            changes.get("price_min", current["priceMin"]),
            changes.get("price_max", current["priceMax"]),
            changes.get("radius_m", current["radiusM"]),
        )
        kind = current["kindTag"]
        if "kind_tag" in changes:
            wanted = changes["kind_tag"]
            kind = None
            if wanted is not None:
                tags = [{"id": t["id"], "name": t["name"]} for t in out["knownTags"] if t["id"] == wanted]
                kind = tags[0] if tags else None
                if kind is None:
                    raise Refusal("unknown_tag")
        current.update(merged)
        current["kindTag"] = kind
        current["setBy"] = "organiser"

    return update_outing(doc, ws_id, outing_id, change, stale=True)


def token_free(out: Mapping) -> dict:
    """A copy of an outing without its members' tokens: the one view a page, an agent or a log may see."""
    view = copy.deepcopy(dict(out))
    for m in view["members"]:
        del m["token"]
    return view


def resolved_ids(m: Mapping) -> list[str]:
    return [f["resolved"] for f in m["favourites"] if f["resolved"]]


def members_without_a_match(out: Mapping) -> list[str]:
    return [m["id"] for m in out["members"] if not resolved_ids(m)]


def all_resolved_ids(out: Mapping) -> list[str]:
    seen: list[str] = []
    for m in out["members"]:
        seen += [e for e in resolved_ids(m) if e not in seen]
    return seen


def member_entities(out: Mapping) -> dict[str, list[str]]:
    return {m["id"]: resolved_ids(m) for m in out["members"]}


def favourite_by_entity(m: Mapping) -> dict[str, str]:
    return {f["resolved"]: f["id"] for f in m["favourites"] if f["resolved"]}


def log_activity(
    doc: dict, ws_id: str, *, actor: str, as_: str | None, tool: str, outcome: str, now: float
) -> dict:
    entry = {"ts": iso(now), "actor": actor, "as": as_, "tool": tool, "outcome": outcome}

    def change(ws: dict) -> None:
        ws["activityLog"] = [*ws["activityLog"], entry][-MAX_LOGGED_ACTIVITY:]

    return _with_workspace(doc, ws_id, change)


def ledger_label(ws_id: str) -> str:
    """What the call log says about a workspace: a hash, because the id itself is the organiser's cookie."""
    return "w_" + hashlib.sha256(ws_id.encode()).hexdigest()[:8]


def log_call(
    doc: dict, *, path: str, cache: str, ms: int, started_by: str, workspace_id: str, now: float
) -> dict:
    """One line per Qloo call: time, path, cache or miss, milliseconds and who started it. No query value."""
    entry = {
        "ts": iso(now),
        "path": path,
        "cache": cache,
        "ms": ms,
        "startedBy": started_by,
        "workspace": workspace_id,
    }
    return {**doc, "calls": [*doc["calls"], entry][-MAX_LOGGED_CALLS:]}
