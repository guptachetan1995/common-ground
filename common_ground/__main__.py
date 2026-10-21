"""python3 -m common_ground <command>"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Mapping, TextIO

from . import fair_share, keyday, mcp_stdio, measured, outings, settings, sources, web, wire
from .gateway import Actor, Gateway
from .refusal import Refusal

SETUP_REFUSALS = ("no_key", "shapes_unverified", "bad_base_url")
SYNTHETIC_BANNER = "Synthetic sample data. Qloo is not being called."
HEADLINES = {
    "common": "{n} common place(s) shown: in the upper half of every person's own ranking",
    "none_shared": "no place is shared by everyone; the closest places name who each one leaves out",
    "none_close": "no place comes close: Qloo ranked only part of the long list, so most places count as "
                  "outside most people's upper halves",
    "thin_list": "too few places came back to compare people; nothing was ranked",
    "unranked": "the places were found, but no one has been ranked yet",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m common_ground")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser(
        "probe",
        help="key day: check Qloo's response shapes with at most 14 calls; prints shapes, never a value",
    )
    probe.add_argument(
        "--favourite", action="append", required=True, metavar="NAME",
        help="three times, in this order: a restaurant, a band, a film",
    )
    probe.add_argument(
        "--base-url", default=wire.BASE_URL, help="only Qloo's hackathon host or a local stub is accepted"
    )
    plan = commands.add_parser(
        "plan", help="walk a scenario file through the tools the page uses, and print the trace"
    )
    plan.add_argument("scenario", help="a scenario file such as scenarios/friday-table.json")
    plan.add_argument(
        "--provider", choices=("fake", "live"), default=None,
        help="fake is invented data and makes no network call; live needs a key (default: from the settings)",
    )
    plan.add_argument(
        "--as", dest="actor", choices=("organiser", "agent"), default="organiser",
        help="organiser: you take Qloo's first candidate for every favourite and the first tag; "
             "agent: the walk stops at the first step only a person may take",
    )
    plan.add_argument(
        "--base-url", default=wire.BASE_URL, help="only Qloo's hackathon host or a local stub is accepted"
    )
    commands.add_parser(
        "serve", help="serve the page, the API and the MCP endpoint (synthetic data unless a key is set)"
    )
    mcp = commands.add_parser(
        "mcp", help="a stdio MCP server relaying to a hosted agent address; it needs no key or settings"
    )
    mcp.add_argument(
        "--address", required=True, metavar="URL", help="the agent address the organiser's page shows"
    )
    budget = commands.add_parser(
        "budget", help="the limits in force and the key status; with a scenario, the calls it would make"
    )
    budget.add_argument("scenario", nargs="?", help="a scenario file, to count the calls it would make")
    return parser


def _probe(args: argparse.Namespace, config: settings.Settings, out: TextIO) -> int:
    if len(args.favourite) != 3:
        print("common_ground: --favourite is needed three times: restaurant, band, film", file=sys.stderr)
        return 2
    report = keyday.run(args.favourite, settings.require_key(config), base_url=args.base_url)
    print(report.render(), file=out)
    return 0 if all(report.passed[t] for t in ("T1", "T2", "T3")) else 1


def _scenario(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return outings.scenario_args(json.load(fh))
    except (OSError, ValueError, KeyError, TypeError):
        print(f"common_ground: {path}: not a readable scenario file", file=sys.stderr)
        return None


class _Walk:
    """The sample group's journey through `dispatch`, one printed line per step."""

    def __init__(self, gateway: Gateway, actor: Actor, out: TextIO) -> None:
        self.gateway, self.actor, self.out = gateway, actor, out
        self.outing_id = ""
        self.refused: str | None = None
        self.detail = ""

    def step(self, label: str, tool: str, args: dict) -> dict | None:
        answer = self.gateway.dispatch(tool, args, self.actor)
        verdict = "ok" if answer["ok"] else f"refused ({answer['outcome']})"
        print(f"  {label:<40} {verdict}", file=self.out)
        if not answer["ok"]:
            self.refused, self.detail = answer["outcome"], answer["error"]["detail"]
            return None
        return answer["result"]

    def outing(self) -> dict:
        return outings.outing(self.gateway.document, self.actor.workspace, self.outing_id)

    def favourites(self):
        return [(m["id"], f["id"], f) for m in self.outing()["members"] for f in m["favourites"]]

    def go(self, scenario: dict, as_agent: bool) -> dict | None:
        opened = self.step("open_outing", "open_outing", scenario)
        if opened is None:
            return None
        self.outing_id = opened["outingId"]
        for member_id, favourite_id, _ in self.favourites():
            asked = {"outing_id": self.outing_id, "member_id": member_id, "favourite_id": favourite_id}
            if self.step(f"look_up_favourite {member_id} {favourite_id}", "look_up_favourite", asked) is None:
                return None
        tags = None
        if scenario.get("kind_query"):
            asked = {"outing_id": self.outing_id, "query": scenario["kind_query"]}
            tags = self.step("look_up_kind", "look_up_kind", asked)
            if tags is None:
                return None
        for member_id, favourite_id, favourite in self.favourites():
            asked = {"outing_id": self.outing_id, "member_id": member_id, "favourite_id": favourite_id,
                     "entity_id": favourite["candidates"][0]["entityId"]}
            if self.step(f"resolve_match {member_id} {favourite_id}", "resolve_match", asked) is None:
                if as_agent:
                    self.refused = None
                    print("stopped: only a person can say which match was meant; the agent's part ends here",
                          file=self.out)
                return None
        if tags is not None:
            asked = {"outing_id": self.outing_id, "kind_tag": tags["tags"][0]["id"]}
            if self.step("change_conditions (the kind of place)", "change_conditions", asked) is None:
                return None
        return self.step("run_comparison", "run_comparison", {"outing_id": self.outing_id})


def _trace_lines(out: dict) -> list[str]:
    names = {m["id"]: m["name"] for m in out["members"]}
    limit = out["budget"]["limit"]
    lines = []
    for e in out["trace"]:
        call = f"{e['request']['path']} {e['cache']}" if e["request"] else "-"
        refused = "" if e["outcome"] == "ok" else f" [{e['outcome']}]"
        lines.append(
            f"{e['step']:>3}  {e['actor']:<6} {e['tool']:<18} {names.get(e['member'], ''):<6} {call:<22} "
            f"{e['callsSpent']:>2}/{limit}  {e['because']}{refused}"
        )
    return lines


def _result_lines(result: dict) -> list[str]:
    lines = ["result: " + HEADLINES[result["outcome"]].format(n=len(result["common"]))]
    for label, rows in (("common", result["common"]), ("near", result["near"])):
        for i, place in enumerate(rows, 1):
            ranks = " · ".join(f"{name} {rank}" for name, rank in place["ranks"].items())
            left = f"; leaves out {', '.join(place['leftOut'])}" if place["leftOut"] else ""
            by = f"; ordered by {place['placedBy'].replace('_', ' ')}" if place["placedBy"] else ""
            lines.append(f"  {label} {i}. {place['name']}: {ranks}{left}{by}")
    if result["chance"]:
        lines.append(result["chance"])
    for name, got in result["partialRankings"].items():
        lines.append(f"Qloo ranked only {got['ranked']} of {got['of']} places for {name}")
    if result["unranked"]:
        lines.append(f"not ranked: {', '.join(result['unranked'])}")
    lines.append(
        f"calls: {result['callsSpent']} of {result['callLimit']} used, {result['saved']} not spent; "
        f"stopped because: {result['stoppedBecause']}"
    )
    return lines


def _plan(args: argparse.Namespace, config: settings.Settings, out: TextIO) -> int:
    scenario = _scenario(args.scenario)
    if scenario is None:
        return 2
    chosen = dataclasses.replace(config, provider=args.provider or config.provider)
    source = sources.make(chosen, base_url=args.base_url)
    gateway = Gateway(source, chosen)
    ws = gateway.new_workspace()
    as_agent = args.actor == "agent"
    walk = _Walk(gateway, Actor.agent(ws) if as_agent else Actor.organiser(ws), out)
    print(SYNTHETIC_BANNER if not source.live else f"Live: Qloo is being called (key: {gateway.key_status})",
          file=out)
    print("Running as the agent: it may search and compare, and may not say which match was meant."
          if as_agent else
          "Running as the organiser: each favourite is Qloo's first candidate, recorded as resolved by the "
          "organiser, and the kind of place is the first tag Qloo returns.", file=out)
    print("steps", file=out)
    result = walk.go(scenario, as_agent)
    if walk.outing_id:
        print("trace", file=out)
        for line in _trace_lines(walk.outing()):
            print(line, file=out)
    if result:
        for line in _result_lines(result):
            print(line, file=out)
    if walk.refused:
        print(f"stopped: refused ({walk.refused}) {walk.detail}".rstrip(), file=sys.stderr)
        return 2 if walk.refused in SETUP_REFUSALS else 1
    return 0


def _budget(args: argparse.Namespace, config: settings.Settings, out: TextIO) -> int:
    print(f"key: {config.key_status}", file=out)
    print(f"source when serving: {config.provider}", file=out)
    print(f"calls per outing: {config.call_limit} (an organiser can lift it to {fair_share.CALL_LIMIT_MAX})",
          file=out)
    print(f"agent calls per workspace in 24 hours: {config.agent_calls_per_day}", file=out)
    print(f"server calls per UTC day: {config.daily_live_calls}", file=out)
    print(f"cache lifetime: {config.cache_ttl_s} seconds", file=out)
    print("spent so far: 0. Counters live in memory and restart with each run; they are not a calendar day.",
          file=out)
    if args.scenario:
        scenario = _scenario(args.scenario)
        if scenario is None:
            return 2
        members = len(scenario["members"])
        searches = sum(len(m["favourites"]) for m in scenario["members"])
        kind = 1 if scenario.get("kind_query") else 0
        most = searches + kind + 1 + members
        print(f"{args.scenario}: at most {most} calls ({searches} searches, {kind} tag search, "
              f"1 group search, {members} rankings); fewer when no place can be shared by everyone", file=out)
        fits = "fits" if most <= config.call_limit else f"needs the limit lifted to {most}"
        print(f"against the limit of {config.call_limit}: {fits}", file=out)
    return 0


def _serve(args: argparse.Namespace, config: settings.Settings, out: TextIO) -> int:
    settings.require_servable(config)
    source = sources.make(config)
    gateway = Gateway(source, config, sample=sources.FakeSource() if source.live else None)
    server = web.make_server(web.App(gateway), config.bind, config.port)
    host, port = server.server_address[:2]
    if config.bind in settings.LOOPBACK_BINDS:
        print(f"Common Ground is running at http://{'[::1]' if ':' in host else host}:{port}/", file=out)
    else:
        print(f"Common Ground is listening on {host}:{port}; reach it through the host's HTTPS address, "
              "because the person gate needs HTTPS", file=out)
    print(SYNTHETIC_BANNER if not source.live else f"Live: Qloo is being called (key: {gateway.key_status})",
          file=out)
    if source.live:
        print("Once the day's live calls are spent, a new outing runs on invented sample data and says so; "
              "an outing opened live stops with daily_ceiling_spent and is never switched.", file=out)
    if source.live and measured.UNVERIFIED:
        print("Live calls are refused until the key-day probe has checked Qloo's response shapes "
              "(shapes_unverified).", file=out)
    print("Press Ctrl+C to stop. Workspaces live in memory and go when the program stops.", file=out)
    out.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


COMMANDS = {"probe": _probe, "plan": _plan, "budget": _budget, "serve": _serve}


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    cwd: str = ".",
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "mcp":
        return mcp_stdio.run(args.address, sys.stdin.buffer, sys.stdout.buffer, sys.stderr)
    try:
        config = settings.load(None if environ is None else dict(environ), cwd)
        return COMMANDS[args.command](args, config, sys.stdout if out is None else out)
    except settings.SettingsError as error:
        print(f"common_ground: {error}", file=sys.stderr)
        return 2
    except Refusal as error:
        print(f"common_ground: refused ({error.code}): {error.detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
