"""`python3 -m common_ground mcp --address <agent address>`: a stdio MCP server that relays to a hosted agent.

A client that can only launch a subprocess speaks newline-delimited JSON-RPC to this program. Each line
becomes one POST to `<address>/mcp` and the answer goes back as one line. The relay has no tools of its own,
so the client sees exactly what the hosted endpoint offers: the registry, called as the agent, in which a
human-only verb is an unknown tool. stdio has no header layer, so the three headers the endpoint reads are
derived from the message, and for the 2025 revisions the version that `initialize` agreed on is sent with
every later request. Requests are answered one at a time, in order.

The address holds the agent's token. It is never written to stdout, stderr or an error, and a reply from the
hosted server is passed on only when it is a JSON-RPC message; anything else is replaced by a fixed sentence.
"""
from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, TextIO

from . import mcp_http

MAX_LINE = 64 * 1024
MAX_REPLY = 4 * 1024 * 1024
TIMEOUT_S = 180
SERVER_ERROR = -32000
LOOPBACK = ("127.0.0.1", "localhost", "::1")
USER_AGENT = "common-ground-mcp-relay"

NOT_SHAPED = "--address must look like https://<host>/agent/<token>, as the page shows it"
CLEAR_TEXT = "--address must be https unless it is a loopback address, or the token would travel in clear"
NOT_JSON = "The line is not JSON"
BATCH = "One JSON-RPC message to a line is accepted; a batch is not"
NO_METHOD = "A JSON-RPC request or notification with a method is needed"
UNREACHABLE = "The hosted server could not be reached, or did not answer in time"
UNKNOWN_ADDRESS = (
    "The hosted server does not know this agent address; it may have restarted, and workspaces live in memory"
)
LIMITED = "The hosted server is limiting requests to this agent address"
OTHER_STATUS = "The hosted server answered with status {} and no JSON-RPC message"

Send = Callable[[str, "dict[str, str]", bytes], "Reply"]


class AddressError(ValueError):
    """Its text never carries the address that was refused."""


class Unreachable(Exception):
    pass


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    retry_after: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the token to whatever host it names."""

    def redirect_request(self, *args, **kwargs):
        return None


def endpoint(address: str) -> str:
    try:
        parts = urllib.parse.urlsplit(address.strip())
        host, _ = parts.hostname, parts.port
    except ValueError:
        raise AddressError(NOT_SHAPED) from None
    path = parts.path.rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")]
    segments = path.split("/")
    shaped = (
        parts.scheme in ("http", "https") and host and not (parts.query or parts.fragment or parts.username)
        and len(segments) == 3 and segments[:2] == ["", "agent"] and segments[2]
    )
    if not shaped:
        raise AddressError(NOT_SHAPED)
    if parts.scheme == "http" and host not in LOOPBACK:
        raise AddressError(CLEAR_TEXT)
    return f"{parts.scheme}://{parts.netloc}{path}/mcp"


def post(url: str, headers: dict[str, str], body: bytes) -> Reply:
    handlers: list[Any] = [_NoRedirect()]
    if urllib.parse.urlsplit(url).hostname in LOOPBACK:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=TIMEOUT_S) as response:
            return Reply(response.status, response.read(MAX_REPLY + 1))
    except urllib.error.HTTPError as error:
        try:
            return Reply(error.code, error.read(MAX_REPLY + 1), error.headers.get("Retry-After"))
        except (OSError, http.client.HTTPException):
            raise Unreachable from None
        finally:
            error.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise Unreachable from None


def _line(message: Any) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode("ascii")


def _error(request_id: Any, code: int, message: str) -> bytes:
    usable = isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
    error = {"code": code, "message": message}
    return _line({"jsonrpc": "2.0", "id": request_id if usable else None, "error": error})


def _name_header(name: str) -> str:
    plain = name.isascii() and name.isprintable() and name == name.strip()
    return name if plain else "=?base64?" + base64.b64encode(name.encode("utf-8")).decode("ascii") + "?="


def _upstream_failure(request_id: Any, reply: Reply) -> bytes:
    if reply.status == 404:
        return _error(request_id, SERVER_ERROR, UNKNOWN_ADDRESS)
    if reply.status == 429:
        wait = reply.retry_after if reply.retry_after and reply.retry_after.isdigit() else None
        return _error(request_id, SERVER_ERROR, LIMITED + (f"; retry in {wait} s" if wait else ""))
    return _error(request_id, SERVER_ERROR, OTHER_STATUS.format(reply.status))


def _is_message(body: Any) -> bool:
    return isinstance(body, dict) and body.get("jsonrpc") == "2.0" and ("result" in body or "error" in body)


class Relay:
    def __init__(self, url: str, send: Send, stderr: TextIO) -> None:
        self.url, self.send, self.stderr = url, send, stderr
        self.agreed: str | None = None

    def headers(self, message: dict) -> dict[str, str]:
        sent = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                "User-Agent": USER_AGENT}
        params = message.get("params")
        meta = params.get("_meta") if isinstance(params, dict) else None
        version = meta.get(mcp_http.META_VERSION) if isinstance(meta, dict) else None
        if isinstance(version, str):
            sent["MCP-Protocol-Version"] = version
            sent["Mcp-Method"] = message["method"]
            if message["method"] == "tools/call" and isinstance(params.get("name"), str):
                sent["Mcp-Name"] = _name_header(params["name"])
        elif message["method"] != "initialize" and self.agreed:
            sent["MCP-Protocol-Version"] = self.agreed
        return sent

    def answer(self, raw: bytes) -> bytes | None:
        """The one line to write for one line read, or None where JSON-RPC wants no answer."""
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _error(None, mcp_http.PARSE_ERROR, NOT_JSON)
        if not isinstance(message, dict):
            return _error(None, mcp_http.INVALID_REQUEST, BATCH)
        request_id = message.get("id")
        if not isinstance(message.get("method"), str):
            if "id" in message and ("result" in message or "error" in message):
                self.stderr.write("common_ground mcp: a response from the client was ignored\n")
                return None
            return _error(request_id, mcp_http.INVALID_REQUEST, NO_METHOD)
        try:
            reply = self.send(self.url, self.headers(message), raw)
        except Unreachable:
            if "id" in message:
                return _error(request_id, SERVER_ERROR, UNREACHABLE)
            self.stderr.write("common_ground mcp: a notification could not be delivered\n")
            return None
        return self.passed_on(request_id, message, reply) if "id" in message else None

    def passed_on(self, request_id: Any, message: dict, reply: Reply) -> bytes:
        try:
            if len(reply.body) > MAX_REPLY:
                raise ValueError
            body = json.loads(reply.body)
        except ValueError:
            return _upstream_failure(request_id, reply)
        if not _is_message(body):
            return _upstream_failure(request_id, reply)
        result = body.get("result")
        if message["method"] == "initialize" and isinstance(result, dict):
            if result.get("protocolVersion") in mcp_http.LEGACY:
                self.agreed = result["protocolVersion"]
        return _line(body)


def _read(stdin: BinaryIO) -> tuple[bytes | None, bool]:
    """The next line without its newline, and whether it ran past MAX_LINE (then the rest is drained)."""
    line = stdin.readline(MAX_LINE + 1)
    if not line:
        return None, False
    if len(line) > MAX_LINE and not line.endswith(b"\n"):
        rest = stdin.readline(MAX_LINE)
        while rest and not rest.endswith(b"\n"):
            rest = stdin.readline(MAX_LINE)
        return b"", True
    return line.rstrip(b"\r\n"), False


def run(address: str, stdin: BinaryIO, stdout: BinaryIO, stderr: TextIO, send: Send = post) -> int:
    try:
        url = endpoint(address)
    except AddressError as error:
        stderr.write(f"common_ground: {error}\n")
        return 2
    relay = Relay(url, send, stderr)
    host = urllib.parse.urlsplit(url).netloc
    stderr.write(f"common_ground mcp: relaying to {host}; closing stdin ends it\n")
    stderr.flush()
    try:
        while True:
            raw, too_long = _read(stdin)
            if raw is None:
                return 0
            if too_long:
                reply = _error(None, mcp_http.INVALID_REQUEST, f"A line is limited to {MAX_LINE} bytes")
            elif raw.strip():
                reply = relay.answer(raw)
            else:
                continue
            if reply is not None:
                stdout.write(reply + b"\n")
                stdout.flush()
    except BrokenPipeError:
        return 0
