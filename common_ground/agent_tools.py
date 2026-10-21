"""The tools an agent may call, and nothing else.

A tool's description is all a model reads, so each one is written for a reader who cannot see the screen
and says what the tool does not do. The human-only verbs live in person_verbs and are never in this
registry: an agent cannot list them, and the gateway refuses them for an agent that names one anyway.
Each handler takes the gateway's Context and the validated arguments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import comparison, drafts, outings, qloo_calls, records
from .refusal import Refusal

PERSON = "person"
OUTING_ID = {"type": "string", "description": "The outing's id, as open_outing returned it."}
MEMBER_ID = {"type": "string", "description": "A member's id inside the outing, such as m1."}
PLACE_ID = {"type": "string", "description": "A place's id, as run_comparison or read_outing returned it."}
CONDITIONS_NOT_SENT = "The label, the people's names and `when` are never sent to Qloo."


@dataclass(frozen=True)
class Args:
    """The arguments a tool or verb declares, and which of them must be present."""

    declared: dict
    required: tuple[str, ...] = ()

    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": self.declared,
            "required": list(self.required),
            "additionalProperties": False,
        }


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: Args
    run: Callable[..., Any]


def open_outing(ctx, **args) -> dict:
    ws = ctx.actor.workspace
    source = ctx.gateway.new_outing_source()
    made: list[str] = []

    def add(doc: dict) -> dict:
        doc, outing_id = outings.open_outing(
            doc, ws, args, token=ctx.token, now=ctx.now(), call_limit=ctx.config.call_limit,
            source=source,
        )
        made.append(outing_id)
        return doc

    ctx.commit(add)
    out = outings.outing(ctx.doc, ws, made[0])
    members = [{"id": m["id"], "name": m["name"]} for m in out["members"]]
    if ctx.actor.kind == PERSON:
        for shown, m in zip(members, out["members"]):
            shown["link"] = "/m/" + m["token"]
    return {"outingId": out["id"], "organiser": out["members"][0]["id"], "members": members,
            "callLimit": out["budget"]["limit"], "source": out["source"]}


def look_up_favourite(ctx, outing_id, member_id, favourite_id) -> dict:
    out = ctx.outing(outing_id)
    member = outings.member(out, member_id)
    favourite = outings.favourite(member, favourite_id)
    ws = ctx.actor.workspace

    def keep(found) -> None:
        ctx.commit(lambda doc: outings.store_candidates(
            doc, ws, out["id"], member["id"], favourite["id"], found
        ))

    with ctx.spending(out, "look_up_favourite") as spend:
        try:
            found = spend.call(
                qloo_calls.search_request(favourite["name"]),
                f"one search so a person can say which match {member['name']}'s favourite "
                f"{favourite['id']} meant",
                member=member["id"],
                read=records.read_search,
            )
        except Refusal as error:
            if error.code == records.NO_RESULTS:
                keep([])
            raise
        keep(found.candidates)
        if found.dropped_people:
            spend.note(
                f"{found.dropped_people} candidate(s) typed as a person were dropped: "
                "a favourite is never a person",
                member=member["id"],
            )
    return {
        "outingId": out["id"], "memberId": member["id"], "favouriteId": favourite["id"],
        "candidates": [
            {"entityId": c.entity_id, "name": c.name, "type": c.type, "popularity": c.popularity,
             "disambiguation": c.disambiguation}
            for c in found.candidates
        ],
        "droppedPeople": found.dropped_people,
        "callsSpent": spend.spent,
    }


def look_up_kind(ctx, outing_id, query) -> dict:
    out = ctx.outing(outing_id)
    word = outings.text(query, "query", outings.MAX_FAVOURITE)
    with ctx.spending(out, "look_up_kind") as spend:
        tags = spend.call(
            qloo_calls.tags_request(word), "one search for a tag that names the kind of place",
            read=records.read_tags,
        )
        ctx.commit(lambda doc: outings.store_known_tags(doc, ctx.actor.workspace, out["id"], tags))
    return {
        "outingId": out["id"],
        "tags": [{"id": t.id, "name": t.name, "type": t.type} for t in tags],
        "callsSpent": spend.spent,
    }


def run_comparison(ctx, outing_id, max_calls=None, complete=None) -> dict:
    out = ctx.outing(outing_id)
    if max_calls is not None and max_calls < 0:
        raise Refusal(outings.BAD_ARGUMENTS, "max_calls")
    with ctx.spending(out, "run_comparison", max_calls=max_calls, trace_actor=comparison.AGENT) as spend:
        return comparison.run(out, spend, complete=bool(complete))


def _place_of(out: dict, place_id: str) -> dict:
    for place in out["places"]:
        if place["entityId"] == place_id:
            return place
    raise Refusal("unknown_place")


def show_evidence(ctx, outing_id, place_id) -> dict:
    out = ctx.outing(outing_id)
    place = _place_of(out, place_id)
    names = {m["id"]: m for m in out["members"]}
    favourite_names = {f["id"]: f["name"] for m in out["members"] for f in m["favourites"]}
    return {
        "placeId": place["entityId"], "name": place["name"], "status": place["status"],
        "placedBy": place["placedBy"], "rule": _rule(place), "stale": bool(out["comparison"]["stale"]),
        "tags": place["tags"], "address": place["address"], "website": place["website"],
        "leftOut": [names[m]["name"] for m in place["leftOut"]],
        "members": [
            {
                **{k: entry[k] for k in ("member", "rank", "affinity", "band", "inUpperHalf")},
                "name": names[entry["member"]]["name"],
                "because": [
                    {"favourite": line["favourite"], "name": favourite_names[line["favourite"]],
                     "score": line["score"]}
                    for line in entry["because"]
                ],
                "restsOnOrganiserResolution": entry["restsOnOrganiserResolution"],
            }
            for entry in place["perMember"]
        ],
    }


def _rule(place: dict) -> str:
    status, by = place["status"], place["placedBy"]
    if status == "common":
        return ("common: in the upper half of every ranked person's own ranking; "
                f"ordered by {by.replace('_', ' ')}")
    if status == "near":
        return "near: outside the upper half for at most half of the people ranked, none of them everyone"
    if status == "ruled_out":
        return "ruled out by the organiser: " + place["ruledOut"]["reason"]
    return "set aside: outside the upper half for more than half of the people ranked"


def write_draft(ctx, outing_id, place_id, kind) -> dict:
    out = ctx.outing(outing_id)
    if out["comparison"] is None:
        raise Refusal("unknown_place")
    if out["comparison"]["stale"]:
        raise Refusal("stale_comparison")
    place = _place_of(out, place_id)
    chosen = out["chosen"] is not None and out["chosen"]["placeId"] == place["entityId"]
    if place["status"] not in ("common", "near") and not chosen:
        raise Refusal("unknown_place")
    draft_id = f"d{len(out['drafts']) + 1}"
    draft = drafts.make_draft(out, place, kind, draft_id, out["revision"] + 1)
    ctx.update(out["id"], lambda o: o["drafts"].append(draft))
    return {"draftId": draft_id, "kind": draft["kind"], "state": draft["state"], "text": draft["text"]}


def read_outing(ctx, outing_id) -> dict:
    return outings.token_free(ctx.outing(outing_id))


def spend_report(ctx) -> dict:
    ws = outings.workspace(ctx.doc, ctx.actor.workspace)
    source = ctx.gateway.source.report()
    allowed = ctx.config.agent_calls_per_day
    used = outings.agent_calls_24h(ws, ctx.now())
    return {
        "key": ctx.gateway.key_status,
        "source": source["source"],
        "outings": [
            {"id": o["id"], "source": o["source"], "spent": o["budget"]["spent"],
             "limit": o["budget"]["limit"],
             "left": max(0, o["budget"]["limit"] - o["budget"]["spent"]), "saved": o["budget"]["saved"],
             "stoppedBecause": o["budget"]["stoppedBecause"]}
            for o in ws["outings"]
        ],
        "agentCalls24h": used,
        "agentAllowance": allowed,
        "agentCallsLeft": max(0, allowed - used),
        "serverCallsToday": source["liveCallsToday"],
        "serverCeiling": source.get("dailyCeiling"),
        "cacheHits": source["cacheHits"],
        "note": "These counters live in memory and restart with the server; they are not a calendar day.",
    }


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool(
        "open_outing",
        "Start a group outing and return its id and each person's id. Give a label, the day of the week "
        "(monday to sunday), an optional price band of 1 to 4 (Qloo's own scale, not an amount of money), a "
        "city or neighbourhood (never an address), and 2 to 6 members, each a short nickname with up to "
        "three favourites typed as the names of public things only (a restaurant, a band, a film, a show, "
        "a book, a brand; never a person). The first member is the organiser. `kind_query` is a word such "
        "as \"restaurant\" for look_up_kind, and `when` is free text used only in drafts. "
        "The result's `source` is `live` or `synthetic`: a synthetic outing is answered from invented sample "
        "data because the server's daily ceiling of live Qloo calls was spent when it opened, and it keeps "
        "that source for its whole life. Does not search Qloo, does not say which match a favourite meant "
        f"(only a person can), and does not choose the kind of place. {CONDITIONS_NOT_SENT}",
        Args({
            "label": {"type": "string", "description": "A name for the outing, at most 60 characters."},
            "members": {"type": "array", "description": "2 to 6 items: {name, favourites[]}."},
            "place_text": {"type": "string", "description": "A city or neighbourhood, up to 60 characters."},
            "day": {"type": "string", "enum": list(qloo_calls.WEEKDAYS)},
            "price_min": {"type": ["integer", "null"], "description": "1 to 4."},
            "price_max": {"type": ["integer", "null"], "description": "1 to 4."},
            "radius_m": {"type": ["integer", "null"], "description": "0 to 50000 metres."},
            "kind_query": {"type": ["string", "null"], "description": "A word for look_up_kind."},
            "when": {"type": ["string", "null"], "description": "Free text for drafts, up to 40 characters."},
        }, ("label", "members", "place_text", "day")),
        open_outing,
    ),
    Tool(
        "look_up_favourite",
        "Ask Qloo once what one typed favourite could mean, and store up to five candidates (id, name, type, "
        "popularity, a note) on that favourite. Spends one call from the outing's limit. Candidates typed as "
        "people are dropped. Does not pick a candidate: a person says which one they meant, and a favourite "
        "nobody has resolved is never used in a comparison.",
        Args({"outing_id": OUTING_ID, "member_id": MEMBER_ID,
                "favourite_id": {"type": "string", "description": "A favourite's id, such as f1."}},
               ("outing_id", "member_id", "favourite_id")),
        look_up_favourite,
    ),
    Tool(
        "look_up_kind",
        "Ask Qloo once for tags that match a word such as \"restaurant\", and store up to ten as the "
        "outing's known tags. Spends one call. Does not choose a tag or set the kind of place: only the "
        "organiser can, and only with a tag this call returned.",
        Args({"outing_id": OUTING_ID,
                "query": {"type": "string", "description": "One word, such as restaurant."}},
               ("outing_id", "query")),
        look_up_kind,
    ),
    Tool(
        "run_comparison",
        "Compare places for the whole group. Needs at least one resolved favourite for every member and no "
        "searched favourite left unresolved. Makes one group search, then one ranking per member (the member "
        "whose favourites shaped the group search least goes first), and stops as soon as no place can be "
        "shared by everyone. Returns the common places, the near places with who each leaves out, the line "
        "comparing the result with chance, the trace, and calls spent and saved. A comparison that is still "
        "current is resumed rather than repeated; `complete: true` also runs the rankings an early stop "
        "skipped. `max_calls` can only lower the outing's call limit. Does not exceed the outing's limit, "
        "the agent's daily allowance or the server's ceiling, does not change a condition, pick a place, "
        "message anyone, or use a favourite no person has resolved.",
        Args({
            "outing_id": OUTING_ID,
            "max_calls": {"type": ["integer", "null"], "description": "A lower limit on the outing's calls."},
            "complete": {"type": ["boolean", "null"], "description": "Also rank whom an early stop skipped."},
        }, ("outing_id",)),
        run_comparison,
    ),
    Tool(
        "show_evidence",
        "Return the stored evidence for one place: for each ranked member their rank, Qloo's affinity and "
        "band, which of their favourites Qloo says explain it, whether the organiser resolved that member's "
        "favourites for them, who the place leaves out, and the rule that placed it. Does not call Qloo and "
        "does not add a claim that is not in a stored response.",
        Args({"outing_id": OUTING_ID, "place_id": PLACE_ID}, ("outing_id", "place_id")),
        show_evidence,
    ),
    Tool(
        "write_draft",
        "Write a DRAFT message for a place that is currently a pick (common or near) or is the chosen place: "
        "`invitation` to the group or `booking_request` to the place. Returns the text, which begins "
        "\"DRAFT. Not signed off. Do not send.\" and has a sender line that still reads \"[sender name "
        "needed]\". Does not invent a time, price or availability, send or address anything, name a sender, "
        "or produce text without the DRAFT line; only the organiser can sign a message off.",
        Args({"outing_id": OUTING_ID, "place_id": PLACE_ID,
                "kind": {"type": "string", "enum": list(drafts.KINDS)}}, ("outing_id", "place_id", "kind")),
        write_draft,
    ),
    Tool(
        "read_outing",
        "Return the whole outing as stored: conditions, members and their favourites with candidates and "
        "who resolved them, the long list, every place with its per-member figures, the budget, the trace, "
        "the chosen place and the drafts. Includes no token or link. Does not write anything or call Qloo.",
        Args({"outing_id": OUTING_ID}, ("outing_id",)),
        read_outing,
    ),
    Tool(
        "spend_report",
        "Return the calls spent and left on each outing in this workspace, the agent's allowance used in "
        "the last 24 hours, the server's calls today against its ceiling, cache hits, and whether a key "
        "is set. Does not call Qloo and never returns the key or any part of it.",
        Args({}),
        spend_report,
    ),
)}


def listing() -> list[dict]:
    """The registry as an MCP client or `GET /api/tools` sees it: name, description and input schema."""
    return [
        {"name": t.name, "description": t.description, "inputSchema": t.args.schema} for t in TOOLS.values()
    ]
