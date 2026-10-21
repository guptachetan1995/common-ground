"""The decisions that stay with people. None of these is a tool: they are reached only by `dispatch` with a
person as the caller, and the registry in agent_tools does not contain them.

Two may also come from a member's own link, for that member alone (`members=True`); the rest need the
organiser. A resolution or a favourite the organiser supplies for someone else is stored as
`organiser_for`, and the organiser's own is a member's own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import drafts, fair_share, outings
from .agent_tools import Args
from .refusal import Refusal

OUTING_ID = {"type": "string"}
REVISION = {"type": "integer", "description": "The outing's revision the person last saw."}
MAX_REASON = 200


@dataclass(frozen=True)
class Verb:
    args: Args
    run: Callable[..., Any]
    members: bool = False


def _provenance(ctx, out: dict, member_id: str) -> str:
    """"member" where the person acts for themself; "organiser_for" where the organiser acts for another."""
    actor = ctx.actor
    if actor.is_member:
        if member_id != actor.member:
            raise Refusal("wrong_member", "a member's own link acts for that member only")
        return "member"
    outings.member(out, member_id)
    return "member" if member_id == out["members"][0]["id"] else "organiser_for"


def _fresh(out: dict, revision: int) -> None:
    if revision != out["revision"]:
        raise Refusal("stale_revision", f"the outing is at revision {out['revision']}")


def _members(out: dict, ids: list) -> None:
    known = {m["id"] for m in out["members"]}
    for member_id in ids:
        if not isinstance(member_id, str) or member_id not in known:
            raise Refusal("unknown_member", str(member_id)[:40])


def resolve_match(ctx, outing_id, member_id, favourite_id, entity_id) -> dict:
    out = ctx.outing(outing_id)
    resolved_by = _provenance(ctx, out, member_id)
    ws = ctx.actor.workspace
    ctx.commit(lambda doc: outings.resolve(
        doc, ws, out["id"], member_id, favourite_id, entity_id, resolved_by
    ))
    candidates = outings.favourite(outings.member(out, member_id), favourite_id)["candidates"]
    name = next(c["name"] for c in candidates if c["entityId"] == entity_id)
    return {"favouriteId": favourite_id, "resolved": name, "resolvedBy": resolved_by}


def add_own_favourite(ctx, outing_id, member_id, name) -> dict:
    out = ctx.outing(outing_id)
    named_by = _provenance(ctx, out, member_id)
    ws = ctx.actor.workspace
    ctx.commit(lambda doc: outings.add_favourite(doc, ws, out["id"], member_id, name, named_by))
    added = outings.member(outings.outing(ctx.doc, ws, out["id"]), member_id)["favourites"][-1]
    return {"favouriteId": added["id"], "name": added["name"], "namedBy": named_by}


def pick_place(ctx, outing_id, place_id, revision, acknowledge_left_out=None) -> dict:
    out = ctx.outing(outing_id)
    _fresh(out, revision)
    if out["comparison"] is None:
        raise Refusal("unknown_place")
    if out["comparison"]["stale"]:
        raise Refusal("stale_comparison")
    place = next((p for p in out["places"] if p["entityId"] == place_id and p["status"] != "ruled_out"), None)
    if place is None:
        raise Refusal("unknown_place")
    said = acknowledge_left_out or []
    _members(out, said)
    unranked = out["comparison"]["unrankedMembers"]
    missing = [m for m in [*place["leftOut"], *unranked] if m not in said]
    if missing:
        raise Refusal("left_out_unacknowledged", ", ".join(missing))
    chosen = {
        "placeId": place["entityId"], "name": place["name"], "status": place["status"],
        "leftOut": place["leftOut"], "unranked": unranked, "acknowledged": list(said),
    }
    ctx.update(out["id"], lambda o: o.update(chosen=chosen))
    return {
        "chosen": place["name"], "status": place["status"], "leftOut": place["leftOut"], "unranked": unranked,
    }


def sign_off_message(ctx, outing_id, draft_id, revision, sender_name=None) -> dict:
    out = ctx.outing(outing_id)
    _fresh(out, revision)
    index = next((i for i, d in enumerate(out["drafts"]) if d["draftId"] == draft_id), None)
    if index is None:
        raise Refusal("unknown_draft")
    if out["drafts"][index]["state"] == "released":
        raise Refusal(outings.BAD_ARGUMENTS, "draft_id")
    released = drafts.release(out["drafts"][index], sender_name, out["revision"] + 1)

    def change(o: dict) -> None:
        o["drafts"][index] = released

    ctx.update(out["id"], change)
    return {"draftId": released["draftId"], "text": released["text"], "signedOffBy": released["signedOffBy"]}


def change_conditions(ctx, outing_id, **changes) -> dict:
    out = ctx.outing(outing_id)
    ws = ctx.actor.workspace
    ctx.commit(lambda doc: outings.set_conditions(doc, ws, out["id"], changes))
    now = outings.outing(ctx.doc, ws, out["id"])
    return {"conditions": now["conditions"], "comparisonMarkedStale": now["comparison"] is not None}


def rule_out_place(ctx, outing_id, place_id, reason=None, undo=None) -> dict:
    out = ctx.outing(outing_id)
    place = next((p for p in out["places"] if p["entityId"] == place_id), None)
    if place is None:
        raise Refusal("unknown_place")
    reason = None if undo else outings.text(reason, "reason", MAX_REASON)

    def change(o: dict) -> None:
        for p in o["places"]:
            if p["entityId"] != place_id:
                continue
            if undo:
                if p["status"] == "ruled_out":
                    p["status"] = p.pop("ruledOut")["was"]
            elif p["status"] != "ruled_out":
                p["ruledOut"] = {"reason": reason, "was": p["status"]}
                p["status"] = "ruled_out"
        if not undo and o["chosen"] and o["chosen"]["placeId"] == place_id:
            o["chosen"] = None

    ctx.update(out["id"], change)
    return {"placeId": place_id, "ruledOut": not undo}


def lift_call_limit(ctx, outing_id, limit) -> dict:
    out = ctx.outing(outing_id)
    wanted = outings.whole(limit, "limit", out["budget"]["limit"] + 1, fair_share.CALL_LIMIT_MAX)
    ctx.update(out["id"], lambda o: o["budget"].update(limit=wanted))
    return {"limit": wanted, "spent": out["budget"]["spent"]}


VERBS: dict[str, Verb] = {
    "resolve_match": Verb(Args({
        "outing_id": OUTING_ID, "member_id": {"type": "string"}, "favourite_id": {"type": "string"},
        "entity_id": {"type": "string"},
    }, ("outing_id", "member_id", "favourite_id", "entity_id")), resolve_match, members=True),
    "add_own_favourite": Verb(Args({
        "outing_id": OUTING_ID, "member_id": {"type": "string"}, "name": {"type": "string"},
    }, ("outing_id", "member_id", "name")), add_own_favourite, members=True),
    "pick_place": Verb(Args({
        "outing_id": OUTING_ID, "place_id": {"type": "string"}, "revision": REVISION,
        "acknowledge_left_out": {"type": ["array", "null"]},
    }, ("outing_id", "place_id", "revision")), pick_place),
    "sign_off_message": Verb(Args({
        "outing_id": OUTING_ID, "draft_id": {"type": "string"}, "sender_name": {"type": ["string", "null"]},
        "revision": REVISION,
    }, ("outing_id", "draft_id", "revision")), sign_off_message),
    "change_conditions": Verb(Args({
        "outing_id": OUTING_ID, "day": {"type": "string"}, "price_min": {"type": ["integer", "null"]},
        "price_max": {"type": ["integer", "null"]}, "place_text": {"type": "string"},
        "radius_m": {"type": ["integer", "null"]}, "kind_tag": {"type": ["string", "null"]},
    }, ("outing_id",)), change_conditions),
    "rule_out_place": Verb(Args({
        "outing_id": OUTING_ID, "place_id": {"type": "string"}, "reason": {"type": ["string", "null"]},
        "undo": {"type": ["boolean", "null"]},
    }, ("outing_id", "place_id")), rule_out_place),
    "lift_call_limit": Verb(Args({
        "outing_id": OUTING_ID, "limit": {"type": "integer"},
    }, ("outing_id", "limit")), lift_call_limit),
}
