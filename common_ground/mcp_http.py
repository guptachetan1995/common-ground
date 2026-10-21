"""The hosted MCP endpoint, `POST /agent/<token>/mcp`: JSON-RPC over Streamable HTTP, two protocol eras on
one path.

A request that carries the 2026-07-28 per-request metadata is served statelessly: no handshake, no
session, and the version, method and tool name in the headers must agree with the body. A request that
opens with `initialize` is served as 2025-11-25 or 2025-06-18, with no session id minted, and later requests
of those revisions are told apart by their `MCP-Protocol-Version` header. Both eras offer the same two
methods that matter: `tools/list` is the registry in agent_tools and nothing else, and `tools/call` goes
through `Gateway.dispatch` as the agent, so a human-only verb is an unknown tool.

The functions here take parsed headers (lower-case names) and the raw body, and return a status and a JSON
object (or None for an accepted notification), so the web layer only has to guard the door.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Callable, Mapping

from . import agent_tools
from .gateway import Actor, Gateway

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18")
SUPPORTED = (MODERN, *LEGACY)
SERVER_NAME = "common-ground"
SERVER_VERSION = "1.0.0"

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022

ACCEPTED_NOTIFICATIONS = ("notifications/initialized", "notifications/cancelled")
SHOWN = 64
CACHE_MS = {"server/discover": 3_600_000, "tools/list": 300_000}

INSTRUCTIONS = (
    "Common Ground looks for the places where nobody in a group is left out, using Qloo. An agent here can "
    "open an outing, search Qloo for a favourite or a kind of place, compare places, read the evidence and "
    "write a DRAFT message. Choosing which match a favourite meant, picking a place, signing a message off, "
    "changing the conditions and raising a limit are people's decisions: they are not offered as tools and "
    "are made on the page. Every figure the tools return is Qloo's or says it is this app's rule."
)


class Rpc(Exception):
    """A JSON-RPC error and the HTTP status it travels with."""

    def __init__(self, status: int, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.data = status, code, message, data

    def body(self, request_id: Any) -> dict:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


Answer = tuple[int, "dict | None"]


def _shown(value: Any) -> str:
    return str(value)[:SHOWN]


def _accepts(headers: Mapping[str, str]) -> None:
    """The client must list both response types, though the answer is always one JSON object."""
    listed = [part.split(";")[0].strip().lower() for part in headers.get("accept", "").split(",")]

    def takes(kind: str) -> bool:
        major = kind.split("/")[0] + "/*"
        return any(item in (kind, major, "*/*") for item in listed)

    if not (takes("application/json") and takes("text/event-stream")):
        raise Rpc(406, INVALID_REQUEST, "Accept must list application/json and text/event-stream")


def _parse(raw: bytes) -> dict:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Rpc(400, PARSE_ERROR, "The body is not JSON") from None
    if not isinstance(message, dict):
        raise Rpc(400, INVALID_REQUEST, "The body must be one JSON-RPC request or notification")
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        raise Rpc(400, INVALID_REQUEST, "A JSON-RPC 2.0 request or notification with a method is needed")
    if "id" in message:
        request_id = message["id"]
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            raise Rpc(400, INVALID_REQUEST, "The id must be a string or an integer")
    return message


def _params(message: Mapping) -> dict:
    params = message.get("params")
    return params if isinstance(params, dict) else {}


def _decoded(value: str) -> str | None:
    """A header value, with the Base64 sentinel form decoded."""
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[len("=?base64?"):-len("?=")], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    return value


def respond(gateway: Gateway, workspace: str, headers: Mapping[str, str], raw: bytes) -> Answer:
    """Answer one POST to the MCP endpoint of one workspace."""
    request_id = None
    try:
        _accepts(headers)
        message = _parse(raw)
        request_id = message.get("id")
        if "id" not in message:
            return _notification(message), None
        result = _route(gateway, workspace, message, headers)
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Rpc as error:
        return error.status, error.body(request_id)


def _notification(message: Mapping) -> int:
    if message["method"] not in ACCEPTED_NOTIFICATIONS:
        raise Rpc(404, METHOD_NOT_FOUND, f"Method not found: {_shown(message['method'])}")
    return 202


def _route(gateway: Gateway, workspace: str, message: dict, headers: Mapping[str, str]) -> dict:
    meta = _params(message).get("_meta")
    method = message["method"]
    if method == "initialize":
        return _initialize(_params(message))
    if (isinstance(meta, dict) and META_VERSION in meta) or headers.get("mcp-protocol-version") == MODERN:
        _check_modern_envelope(message, headers)
        handler = _MODERN.get(method)
        if handler is None:
            raise Rpc(404, METHOD_NOT_FOUND, f"Method not found: {_shown(method)}")
        _check_name_header(message, headers)
        result = {
            "resultType": "complete",
            **handler(gateway, workspace, _params(message), True),
            "_meta": {META_SERVER_INFO: _server_info()},
        }
        if method in CACHE_MS:
            result.update(ttlMs=CACHE_MS[method], cacheScope="public")
        return result
    sent = headers.get("mcp-protocol-version")
    if sent not in LEGACY:
        raise Rpc(
            400, UNSUPPORTED_VERSION,
            "This endpoint serves protocol revisions " + ", ".join(SUPPORTED)
            + "; send MCP-Protocol-Version or the 2026-07-28 request metadata",
            {"supported": list(SUPPORTED), "requested": None if sent is None else _shown(sent)},
        )
    handler = _LEGACY.get(method)
    if handler is None:
        raise Rpc(200, METHOD_NOT_FOUND, f"Method not found: {_shown(method)}")
    return handler(gateway, workspace, _params(message), False)


def _check_modern_envelope(message: Mapping, headers: Mapping[str, str]) -> None:
    meta = _params(message).get("_meta")
    version = meta.get(META_VERSION) if isinstance(meta, dict) else None
    if not isinstance(version, str):
        raise Rpc(400, INVALID_PARAMS, f"_meta.{META_VERSION} is required on every request")
    sent = headers.get("mcp-protocol-version")
    if sent is None:
        raise Rpc(400, HEADER_MISMATCH, "The MCP-Protocol-Version header is required")
    if sent != version:
        raise Rpc(400, HEADER_MISMATCH, f"MCP-Protocol-Version {_shown(sent)} does not match the body")
    if version != MODERN:
        raise Rpc(
            400, UNSUPPORTED_VERSION, "Unsupported protocol version",
            {"supported": list(SUPPORTED), "requested": _shown(version)},
        )
    if not isinstance(meta.get(META_CAPABILITIES), dict):
        raise Rpc(400, INVALID_PARAMS, f"_meta.{META_CAPABILITIES} is required on every request")
    if headers.get("mcp-method") != message["method"]:
        raise Rpc(400, HEADER_MISMATCH, "The Mcp-Method header is missing or does not match the request body")


def _check_name_header(message: Mapping, headers: Mapping[str, str]) -> None:
    if message["method"] != "tools/call":
        return
    name = _params(message).get("name")
    if not isinstance(name, str):
        raise Rpc(400, INVALID_PARAMS, "params.name must be a tool name")
    sent = headers.get("mcp-name")
    if sent is None or _decoded(sent) != name:
        raise Rpc(400, HEADER_MISMATCH, "The Mcp-Name header is missing or does not match params.name")


def _server_info() -> dict:
    return {"name": SERVER_NAME, "version": SERVER_VERSION}


def _initialize(params: Mapping) -> dict:
    asked = params.get("protocolVersion")
    if not isinstance(asked, str):
        raise Rpc(200, INVALID_PARAMS, "params.protocolVersion is required")
    return {
        "protocolVersion": asked if asked in LEGACY else LEGACY[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {**_server_info(), "title": "Common Ground"},
        "instructions": INSTRUCTIONS,
    }


def _discover(gateway: Gateway, workspace: str, params: Mapping, modern: bool) -> dict:
    return {
        "supportedVersions": list(SUPPORTED),
        "capabilities": {"tools": {"listChanged": False}},
        "instructions": INSTRUCTIONS,
    }


def _list(gateway: Gateway, workspace: str, params: Mapping, modern: bool) -> dict:
    return {"tools": agent_tools.listing()}


def _ping(gateway: Gateway, workspace: str, params: Mapping, modern: bool) -> dict:
    return {}


def _call(gateway: Gateway, workspace: str, params: Mapping, modern: bool) -> dict:
    status = 400 if modern else 200
    name, arguments = params.get("name"), params.get("arguments")
    if not isinstance(name, str) or not (arguments is None or isinstance(arguments, dict)):
        raise Rpc(status, INVALID_PARAMS, "params.name must be a string and params.arguments an object")
    answer = gateway.dispatch(name, arguments, Actor.agent(workspace))
    if answer["outcome"] == "not_a_tool":
        raise Rpc(status, INVALID_PARAMS, f"Unknown tool: {_shown(name)}", {"outcome": "not_a_tool"})
    if answer["ok"]:
        return {
            "content": [{"type": "text", "text": json.dumps(answer["result"], separators=(",", ":"))}],
            "structuredContent": answer["result"],
            "isError": False,
        }
    refusal = {"outcome": answer["outcome"], "error": answer["error"]}
    text = json.dumps(refusal, separators=(",", ":"))
    return {"content": [{"type": "text", "text": text}], "isError": True}


Handler = Callable[[Gateway, str, Mapping, bool], dict]
_MODERN: dict[str, Handler] = {"server/discover": _discover, "tools/list": _list, "tools/call": _call}
_LEGACY: dict[str, Handler] = {"ping": _ping, "tools/list": _list, "tools/call": _call}
