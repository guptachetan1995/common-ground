"""The two messages, from fixed templates. A draft always carries the DRAFT line; `render` leaves it off
only when it is given a sender's name, so signing off is the only road to text without it.

Nothing here names a price, a time Qloo did not give, or an availability, and no recipient is filled in.
A released text is rendered from the snapshot stored in its draft, never from the outing as it is now.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import outings
from .refusal import Refusal

DRAFT_LINE = "DRAFT. Not signed off. Do not send."
SENDER_NEEDED = "[sender name needed]"
# A sample-source outing never credits Qloo: its rankings and links come from the invented source.
RANKER = {outings.LIVE: "Qloo", outings.SYNTHETIC: "the sample data"}
LEAD_IN = {
    outings.LIVE: "Qloo's taste data, which I used to find it, connects it to ",
    outings.SYNTHETIC: "sample taste data, standing in for Qloo's, connects it to ",
}
KINDS = ("invitation", "booking_request")
MAX_WORDS = 120
MAX_SENDER = 60


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def render(snapshot: Mapping[str, Any], sender_name: str | None = None) -> str:
    sender = SENDER_NEEDED if sender_name is None else sender_name
    if snapshot["kind"] == "invitation":
        body = (
            f"Hi all. I'm suggesting {snapshot['place']} for {snapshot['when']}. "
            f"Why this one: {snapshot['evidence']}. {snapshot['caveat']}Nothing is booked.\n"
            "Tell me if it doesn't work for you, and what would.\n"
            f"{sender}"
        )
    else:
        body = (
            f"Hello. I'm asking whether you have space for {snapshot['people']} people on "
            f"{snapshot['when']}, and what the options are.\n"
            "This message is not a booking and makes no offer.\n"
            f"{sender}"
        )
    return body if sender_name is not None else f"{DRAFT_LINE}\n{body}"


def _clauses(out: Mapping, place: Mapping) -> list[str]:
    """One clause per member whose favourite Qloo's explainability links to the place. The favourite is
    named only when its member resolved it themself."""
    found = []
    for entry in place["perMember"]:
        if not entry["because"]:
            continue
        m = outings.member(out, entry["member"])
        top = max(entry["because"], key=lambda line: line["score"])
        fav = outings.favourite(m, top["favourite"])
        named = "favourites" if fav["resolvedBy"] == "organiser_for" else fav["name"]
        found.append(f"{m['name']}'s {named}")
    return [_one_line(c) for c in found]


def _names(out: Mapping, place: Mapping, inside: bool) -> list[str]:
    names = {m["id"]: m["name"] for m in out["members"]}
    return [names[e["member"]] for e in place["perMember"] if e["inUpperHalf"] == inside]


def _fit(snapshot: dict, clauses: list[str], fallback: str, lead_in: str) -> None:
    """Choose the evidence sentence, dropping clauses from the end until the message fits MAX_WORDS."""
    while True:
        snapshot["evidence"] = lead_in + _join(clauses) if clauses else fallback
        if not clauses or len(render(snapshot).split()) <= MAX_WORDS:
            return
        clauses.pop()


def make_draft(out: Mapping, place: Mapping, kind: str, draft_id: str, revision: int) -> dict:
    if kind not in KINDS:
        raise Refusal(outings.BAD_ARGUMENTS, "kind")
    left, inside = _names(out, place, False), _names(out, place, True)
    ranker = RANKER[out["source"]]
    snapshot = {
        "kind": kind,
        "place": _one_line(place["name"]),
        "when": _one_line(out["when"] or out["conditions"]["day"].capitalize()),
        "people": len(out["members"]),
        "caveat": f"One caveat: {ranker} ranks it outside the upper half for {_join(left)}. " if left else "",
    }
    fallback = (f"it sits in the upper half of each of our rankings, as {ranker} orders them" if not left
                else f"{ranker} ranks it in the upper half for {_join(inside)}")
    _fit(snapshot, _clauses(out, place), fallback, LEAD_IN[out["source"]])
    return {
        "draftId": draft_id,
        "placeId": place["entityId"],
        "kind": kind,
        "state": "draft",
        "text": render(snapshot),
        "snapshot": snapshot,
        "signedOffBy": None,
        "revision": revision,
    }


def release(draft: Mapping, sender_name: Any, revision: int) -> dict:
    """Freeze a draft as released text under a named sender."""
    sender = _one_line(sender_name) if isinstance(sender_name, str) else ""
    if not sender:
        raise Refusal("sender_missing")
    if len(sender) > MAX_SENDER:
        raise Refusal(outings.BAD_ARGUMENTS, "sender_name")
    return {
        **draft,
        "state": "released",
        "text": render(draft["snapshot"], sender),
        "signedOffBy": sender,
        "revision": revision,
    }
