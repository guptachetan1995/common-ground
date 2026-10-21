"""The one place that sends the key or touches the network.

A single attempt per call: retries and counting belong to the caller. The key goes into the X-Api-Key
header and nowhere else. Errors are named from the HTTP status and, for the probe, the shape of Qloo's
error body; nothing here renders an exception's text, a request URL or a response string.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import qloo_calls, records
from .refusal import Refusal

BASE_URL = "https://hackathon.api.qloo.com"
KEY_HEADER = "X-Api-Key"
MAX_BODY = 4 * 1024 * 1024
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")

AUTH = "qloo_auth"
UNSUPPORTED_TYPE = "qloo_unsupported_type"
RATE_LIMITED = "qloo_rate_limited"
BAD_REQUEST = "qloo_bad_request"
UNAVAILABLE = "qloo_unavailable"
BAD_BASE_URL = "bad_base_url"


@dataclass(frozen=True)
class Reply:
    status: int
    body: Any
    ms: int


class QlooError(Refusal):
    def __init__(self, code: str, status: int, shape: dict[str, tuple[str, int]]) -> None:
        super().__init__(code)
        self.status = status
        self.shape = shape


def outcome_for(status: int) -> str:
    if status == 401:
        return AUTH
    if status == 403:
        return UNSUPPORTED_TYPE
    if status == 429:
        return RATE_LIMITED
    if status >= 500 or 300 <= status < 400:
        return UNAVAILABLE
    return BAD_REQUEST


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the key header to whatever host it names."""

    def redirect_request(self, *args, **kwargs):
        return None


def _loopback(base_url: str) -> bool:
    parts = urllib.parse.urlsplit(base_url)
    return parts.scheme == "http" and parts.hostname in LOOPBACK_NAMES


def _opener(base_url: str) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [_NoRedirect()]
    if _loopback(base_url):
        handlers.insert(0, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _error_shape(error: urllib.error.HTTPError) -> dict[str, tuple[str, int]]:
    try:
        return records.skeleton(json.loads(error.read(65536)))
    except (ValueError, OSError, http.client.HTTPException):
        return {}


def send(request: qloo_calls.Request, key: str, *, base_url: str = BASE_URL, timeout: float = 20.0) -> Reply:
    """GET one request. The key only travels to Qloo's hackathon host, or to a loopback stub in a test."""
    if base_url != BASE_URL and not _loopback(base_url):
        raise Refusal(BAD_BASE_URL)
    http_request = urllib.request.Request(
        base_url + request.path + "?" + request.query_string(),
        method="GET",
        headers={KEY_HEADER: key, "Accept": "application/json", "User-Agent": "common-ground"},
    )
    started = time.monotonic()
    try:
        with _opener(base_url).open(http_request, timeout=timeout) as response:
            status = response.status
            raw = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        shape = _error_shape(error)
        error.close()
        raise QlooError(outcome_for(error.code), error.code, shape) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise QlooError(UNAVAILABLE, 0, {}) from None
    if not raw.strip():
        raise QlooError(records.NO_RESULTS, status, {})
    try:
        if len(raw) > MAX_BODY:
            raise ValueError
        body = json.loads(raw)
    except ValueError:
        raise Refusal(records.UNEXPECTED_SHAPE, "$") from None
    return Reply(status, body, int((time.monotonic() - started) * 1000))
