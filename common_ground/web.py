"""The web layer: one request function over `Gateway`, and a bounded stdlib server around it.

`App.handle(Request) -> Response` holds every rule of the route table (host, request label, origin,
credential, content type, size, limits); `make_server` only reads a request off a socket, calls it, and
writes the answer. A page button, the member page, the agent console, the agent address and the MCP endpoint
all end in `Gateway.dispatch`. The document is read as an immutable snapshot and is never serialised:
every view built from it leaves out cookies and tokens, and shows the organiser the agent address and the
member links only when the request is the organiser's.

Who a request is comes from the workspace cookie, the browser's own `Sec-Fetch-Site` label and a header an
agent may add to give itself away; the body never says. A cookie without the label is the agent, not an
error, so a script holding the cookie cannot act as the person.
"""
from __future__ import annotations

import collections
import json
import math
import os
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import agent_tools, fair_share, mcp_http, measured, outings, settings
from .gateway import AGENT, PERSON, Actor, Gateway
from .refusal import Refusal

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB_DIR = os.path.join(ROOT, "web")
SAMPLE_FILE = os.path.join(ROOT, "scenarios", "friday-table.json")

COOKIE = "cg_w"
AGENT_HEADER = "x-common-ground-as"
MAX_BODY = 64 * 1024
DRAIN_MAX = 1 << 20
DISPATCH_PER_MINUTE = 30
CREATE_PER_CLIENT = 30
CREATE_IN_ALL = 120
WINDOW_S = 60.0
MAX_LIMIT_KEYS = 4096
MAX_CLIENT_KEY = 64
MAX_HANDLER_THREADS = 64
READ_TIMEOUT_S = 15

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    ("Content-Security-Policy", CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)
HTML = "text/html; charset=utf-8"
JSON = "application/json; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
PAGES = {
    "/": ("index.html", HTML),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
MEMBER_PAGE = ("member.html", HTML)
MEMBER_SEES = ("id", "name", "namedBy", "searched", "candidates", "resolved", "resolvedBy")


@dataclass(frozen=True)
class Request:
    method: str
    target: str
    headers: Mapping[str, str]
    body: bytes = b""
    peer: str = "127.0.0.1"

    @property
    def path(self) -> str:
        return urlsplit(self.target).path


@dataclass
class Response:
    status: int
    body: bytes = b""
    content_type: str = JSON
    headers: list[tuple[str, str]] = field(default_factory=list)


class Reject(Exception):
    """A guard said no. The answer carries a name, like a refusal from the gateway."""

    def __init__(self, status: int, code: str, detail: str = "", headers: tuple = ()) -> None:
        super().__init__(code)
        self.status, self.code, self.detail, self.headers = status, code, detail, list(headers)


@dataclass(frozen=True)
class Caller:
    actor: Actor
    why: str


def _too_many(wait: float, detail: str) -> Reject:
    return Reject(429, "rate_limited", detail, (("Retry-After", str(math.ceil(wait))),))


def _json(status: int, payload: Any, headers: list | None = None) -> Response:
    return Response(status, json.dumps(payload, separators=(",", ":")).encode(), JSON, headers or [])


def _refusal_body(code: str, detail: str = "") -> dict:
    return {"ok": False, "outcome": code, "error": {"code": code, "detail": detail}}


class Limits:
    """Sliding one-minute windows, kept in memory. A request is counted against every check it names or
    against none, so a refusal by one limit never spends another."""

    def __init__(self, clock) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], collections.deque] = {}
        self._lock = threading.Lock()

    def admit(self, *checks: tuple[str, str, int]) -> float | None:
        """None when admitted; else the seconds until every refused check has a place again."""
        now = self._clock()
        with self._lock:
            waits = []
            for name, key, limit in checks:
                hits = self._hits.get((name, key))
                while hits and now - hits[0] >= WINDOW_S:
                    hits.popleft()
                if hits and len(hits) >= limit:
                    waits.append(WINDOW_S - (now - hits[0]))
            if waits:
                return max(waits)
            for name, key, _ in checks:
                self._hits.setdefault((name, key), collections.deque()).append(now)
            if len(self._hits) > MAX_LIMIT_KEYS:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < WINDOW_S}
            return None


def host_name(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end > 0 else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class App:
    def __init__(self, gateway: Gateway, *, clock=None) -> None:
        self.gateway = gateway
        self.config = gateway.config
        self._allowed = {h.lower() for h in self.config.allowed_hosts}
        self._limits = Limits(clock or gateway.clock)
        self._pages = {path: (self._read(name), kind) for path, (name, kind) in PAGES.items()}
        self._member_page = (self._read(MEMBER_PAGE[0]), MEMBER_PAGE[1])
        with open(SAMPLE_FILE, encoding="utf-8") as fh:
            self._sample = outings.scenario_args(json.load(fh))

    @staticmethod
    def _read(name: str) -> bytes:
        with open(os.path.join(WEB_DIR, name), "rb") as fh:
            return fh.read()

    def handle(self, req: Request) -> Response:
        try:
            response = self._route(req)
        except Reject as no:
            response = _json(no.status, _refusal_body(no.code, no.detail), no.headers)
        except Exception as error:
            sys.stderr.write(f"common_ground: internal error ({type(error).__name__})\n")
            response = _json(500, _refusal_body("internal"))
        response.headers.extend(SECURITY_HEADERS)
        return response

    def _route(self, req: Request) -> Response:
        path = req.path
        if path == "/healthz":
            self._allow(req, "GET", "HEAD")
            return Response(200, b"ok\n", TEXT)
        self._check_host(req)
        parts = path.split("/")
        if path in self._pages:
            self._allow(req, "GET")
            return self._page(req, *self._pages[path], sets_cookie=path == "/")
        if path == "/api/sample":
            self._allow(req, "GET")
            return _json(200, {"args": self._sample})
        if len(parts) == 3 and parts[1] == "m":
            self._allow(req, "GET")
            if outings.find_by_member_token(self.gateway.document, parts[2]) is None:
                raise Reject(404, "not_found")
            return self._page(req, *self._member_page)
        if parts[:2] == ["", "api"]:
            return self._api(req, parts[2:])
        if len(parts) == 4 and parts[1] == "agent":
            return self._agent(req, parts[2], parts[3])
        raise Reject(404, "not_found")

    def _api(self, req: Request, rest: list[str]) -> Response:
        if rest[:1] == ["member"] and len(rest) == 3:
            return self._member(req, rest[1], rest[2])
        if rest == ["dispatch"]:
            self._allow(req, "POST")
            ws_id = self._workspace(req)
            caller = self._caller(req, ws_id)
            self._check_post(req)
            return self._dispatch(req, caller.actor, ("dispatch", ws_id))
        if len(rest) == 1 and rest[0] in ("state", "tools", "calls"):
            self._allow(req, "GET")
            ws_id = self._workspace(req)
            caller = self._caller(req, ws_id)
            if rest[0] == "state":
                return _json(200, self._state(req, ws_id, caller))
            if rest[0] == "tools":
                return _json(200, {"tools": agent_tools.listing()})
            label = outings.ledger_label(ws_id)
            calls = [c for c in self.gateway.document["calls"] if c["workspace"] == label]
            return _json(200, {"calls": calls})
        if len(rest) == 2 and rest[0] == "message" and rest[1].endswith(".txt"):
            self._allow(req, "GET")
            ws_id = self._workspace(req)
            self._caller(req, ws_id)
            return self._message(ws_id, rest[1][: -len(".txt")])
        raise Reject(404, "not_found")

    def _member(self, req: Request, token: str, action: str) -> Response:
        found = outings.find_by_member_token(self.gateway.document, token)
        if found is None or action not in ("state", "dispatch"):
            raise Reject(404, "not_found")
        ws_id, outing_id, member_id = found
        self._allow(req, "POST" if action == "dispatch" else "GET")
        caller = self._caller(req, ws_id, Actor.member_link(ws_id, outing_id, member_id))
        if action == "dispatch":
            self._check_post(req)
            return self._dispatch(req, caller.actor, ("member", token))
        return _json(200, self._member_view(ws_id, outing_id, member_id, caller))

    def _agent(self, req: Request, token: str, action: str) -> Response:
        ws = outings.find_by_agent_token(self.gateway.document, token)
        if ws is None or action not in ("tools", "dispatch", "mcp"):
            raise Reject(404, "not_found")
        if action == "tools":
            self._allow(req, "GET")
            return _json(200, {"tools": agent_tools.listing()})
        self._allow(req, "POST")
        self._check_post(req)
        if action == "dispatch":
            return self._dispatch(req, Actor.agent(ws["id"]), ("agent", token))
        self._admit(("agent", token))
        status, payload = mcp_http.respond(self.gateway, ws["id"], req.headers, req.body)
        return Response(status) if payload is None else _json(status, payload)

    def _allow(self, req: Request, *methods: str) -> None:
        if req.method not in methods:
            raise Reject(405, "method_not_allowed", headers=(("Allow", ", ".join(methods)),))

    def _check_host(self, req: Request) -> None:
        if host_name(req.headers.get("host", "")) not in self._allowed:
            raise Reject(403, "bad_host")

    def _own_origin(self, req: Request) -> str:
        host = req.headers.get("host", "").strip().lower()
        scheme = "http" if host_name(host) in settings.LOOPBACK_HOSTS else "https"
        return f"{scheme}://{host}"

    def _site(self, req: Request) -> str | None:
        site = req.headers.get("sec-fetch-site")
        if site is not None and site not in ("same-origin", "none"):
            raise Reject(403, "cross_site")
        return site

    def _caller(self, req: Request, ws_id: str, person: Actor | None = None) -> Caller:
        """The organiser (or, with `person`, a member's own link) only with the browser's own same-origin
        label and no agent header; anything else is the agent, and says why."""
        site = self._site(req)
        if req.headers.get(AGENT_HEADER) == AGENT:
            return Caller(Actor.agent(ws_id), "agent_header")
        if site == "same-origin":
            return Caller(person or Actor.organiser(ws_id), "same_origin")
        return Caller(Actor.agent(ws_id), "typed_address" if site == "none" else "no_fetch_metadata")

    def _known_workspace(self, req: Request) -> str | None:
        for part in req.headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                known = self.gateway.document["workspaces"]
                return next((ws["id"] for ws in known if ws["id"] == value), None)
        return None

    def _workspace(self, req: Request) -> str:
        found = self._known_workspace(req)
        if found is None:
            raise Reject(401, "no_workspace")
        return found

    def _check_post(self, req: Request) -> None:
        origin = req.headers.get("origin")
        if origin is not None and origin.lower() != self._own_origin(req):
            raise Reject(403, "bad_origin")
        if req.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise Reject(415, "unsupported_media_type", "send application/json")
        if len(req.body) > MAX_BODY:
            raise Reject(413, "body_too_large", f"at most {MAX_BODY} bytes")

    def _admit(self, *checks: tuple[str, str]) -> None:
        wait = self._limits.admit(*((name, key, DISPATCH_PER_MINUTE) for name, key in checks))
        if wait is not None:
            raise _too_many(wait, "too many requests")

    def _dispatch(self, req: Request, actor: Actor, bucket: tuple[str, str]) -> Response:
        self._admit(bucket)
        try:
            body = json.loads(req.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Reject(400, "bad_request", "the body is not JSON") from None
        named = isinstance(body, dict) and isinstance(body.get("tool"), str)
        if not named or set(body) - {"tool", "args"}:
            raise Reject(400, "bad_request", "the body must be {tool, args}")
        return _json(200, self.gateway.dispatch(body["tool"], body.get("args"), actor))

    def _client(self, req: Request) -> tuple[str, str]:
        if self.config.trust_proxy:
            forwarded = req.headers.get("x-forwarded-for", "").split(",")[-1].strip()
            if forwarded:
                return forwarded[:MAX_CLIENT_KEY], "forwarded"
        return req.peer[:MAX_CLIENT_KEY], "peer"

    def _page(self, req: Request, body: bytes, kind: str, *, sets_cookie: bool = False) -> Response:
        headers: list[tuple[str, str]] = []
        if sets_cookie and self._known_workspace(req) is None:
            headers.append(("Set-Cookie", self._new_cookie(req)))
        return Response(200, body, kind, headers)

    def _new_cookie(self, req: Request) -> str:
        client, _ = self._client(req)
        wait = self._limits.admit(("create", client, CREATE_PER_CLIENT), ("create-all", "*", CREATE_IN_ALL))
        if wait is not None:
            raise _too_many(wait, "too many new workspaces")
        cookie = f"{COOKIE}={self.gateway.new_workspace()}; HttpOnly; SameSite=Strict; Path=/"
        if host_name(req.headers.get("host", "")) not in settings.LOOPBACK_HOSTS:
            cookie += "; Secure"
        return cookie

    def _mode(self) -> dict:
        source = self.gateway.source
        return {
            "source": source.name,
            "key": self.gateway.key_status,
            "ceilingSpent": source.exhausted(),
            "newOutingsSynthetic": source.live and self.gateway.new_outing_source() == outings.SYNTHETIC,
            "shapesVerified": not measured.UNVERIFIED,
        }

    def _state(self, req: Request, ws_id: str, caller: Caller) -> dict:
        ws = outings.workspace(self.gateway.document, ws_id)
        report = self.gateway.source.report()
        body: dict[str, Any] = {
            "mode": self._mode(),
            "actor": caller.actor.kind,
            "actorWhy": caller.why,
            "limiterKey": self._client(req)[1],
            "allowances": {
                "agentCalls24h": outings.agent_calls_24h(ws, self.gateway.clock()),
                "agentAllowance": self.config.agent_calls_per_day,
                "serverCallsToday": report["liveCallsToday"],
                "serverCeiling": report.get("dailyCeiling"),
                "cacheHits": report["cacheHits"],
            },
            "callLimit": {"default": self.config.call_limit, "max": fair_share.CALL_LIMIT_MAX},
            "outings": [outings.token_free(o) for o in ws["outings"]],
        }
        if caller.actor.kind == PERSON:
            origin = self._own_origin(req)
            body["agentAddress"] = f"{origin}/agent/{ws['agentToken']}"
            body["memberLinks"] = {
                o["id"]: {m["id"]: f"{origin}/m/{m['token']}" for m in o["members"]} for o in ws["outings"]
            }
        return body

    def _member_view(self, ws_id: str, outing_id: str, member_id: str, caller: Caller) -> dict:
        out = outings.outing(self.gateway.document, ws_id, outing_id)
        mine = outings.member(out, member_id)
        return {
            "mode": self._mode(),
            "actor": caller.actor.kind,
            "actorWhy": caller.why,
            "outing": {"id": out["id"], "label": out["label"], "when": out["when"], "source": out["source"]},
            "member": {
                "id": mine["id"],
                "name": mine["name"],
                "favourites": [{k: f[k] for k in MEMBER_SEES} for f in mine["favourites"]],
            },
        }

    def _message(self, ws_id: str, name: str) -> Response:
        outing_id, _, draft_id = name.partition("-")
        try:
            out = outings.outing(self.gateway.document, ws_id, outing_id)
        except Refusal:
            raise Reject(404, "not_found") from None
        for draft in out["drafts"]:
            if draft["draftId"] == draft_id and draft["state"] == "released":
                return Response(200, draft["text"].encode("utf-8"), TEXT)
        raise Reject(404, "not_found")


class BoundedServer(ThreadingHTTPServer):
    """A threaded server that never runs more than `max_threads` handlers: a request beyond that is
    answered 503 at once, on the accepting thread, rather than queued."""

    daemon_threads = True
    request_queue_size = 128

    def __init__(self, address, handler, app: App, max_threads: int = MAX_HANDLER_THREADS) -> None:
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        self.app = app
        self._slots = threading.BoundedSemaphore(max_threads)
        super().__init__(address, handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address) -> None:
        if not self._slots.acquire(blocking=False):
            self._turn_away(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def _turn_away(self, request) -> None:
        body = json.dumps(_refusal_body("busy", "too many requests at once; try again")).encode()
        head = (
            "HTTP/1.0 503 Service Unavailable\r\nRetry-After: 1\r\nCache-Control: no-store\r\n"
            f"Content-Type: {JSON}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        try:
            request.settimeout(1.0)
            request.sendall(head.encode() + body)
        except OSError:
            pass
        finally:
            self.shutdown_request(request)

    def handle_error(self, request, client_address) -> None:
        sys.stderr.write(f"common_ground: connection error ({sys.exc_info()[0].__name__})\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "CommonGround"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version
    protocol_version = "HTTP/1.0"
    timeout = READ_TIMEOUT_S

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        self._serve()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = do_GET

    def _serve(self) -> None:
        app: App = self.server.app
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            headers.setdefault(name.lower(), value)
        length = headers.get("content-length", "0")
        if "transfer-encoding" in headers or not length.isdigit():
            self._answer(self._early(411, "length_required", "send a Content-Length"))
            return
        size = int(length)
        if size > MAX_BODY:
            if size <= DRAIN_MAX:
                self._drain(size)
            self._answer(self._early(413, "body_too_large", f"at most {MAX_BODY} bytes"))
            return
        body = self.rfile.read(size) if size else b""
        response = app.handle(Request(self.command, self.path, headers, body, self.client_address[0]))
        self._answer(response, head_only=self.command == "HEAD")

    @staticmethod
    def _early(status: int, code: str, detail: str) -> Response:
        response = _json(status, _refusal_body(code, detail))
        response.headers.extend(SECURITY_HEADERS)
        return response

    def _drain(self, size: int) -> None:
        while size > 0:
            chunk = self.rfile.read(min(size, 65536))
            if not chunk:
                return
            size -= len(chunk)

    def _answer(self, response: Response, head_only: bool = False) -> None:
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if not head_only:
                self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass


def make_server(app: App, bind: str, port: int, max_threads: int = MAX_HANDLER_THREADS) -> BoundedServer:
    return BoundedServer((bind, port), Handler, app, max_threads)
