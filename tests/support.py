import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic")
RESERVED = "00000000-0000-4000-8000-"


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def fake_key():
    return "test-" + secrets.token_hex(16)


def conditions(**changes):
    base = {
        "placeText": "Sample City", "day": "friday", "priceMin": 2, "priceMax": 3, "radiusM": None,
        "kindTag": {"id": "urn:tag:synthetic:restaurant", "name": "Restaurant"},
    }
    return {**base, **changes}


def ids(n, start=0):
    return [f"{RESERVED}{0x5000 + start + i:012x}" for i in range(n)]


class Stub:
    """A loopback HTTP server that answers like Qloo from a FakeSource, and records what it was asked."""

    def __init__(self, source, key, echo_key_in_errors=True, delay=0.0):
        self.source, self.key, self.echo, self.delay = source, key, echo_key_in_errors, delay
        self.requests = []
        self.responses = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen = {"command": self.command, "path": self.path, "headers": dict(self.headers)}
                stub.requests.append(seen)
                sent = self.headers.get("X-Api-Key")
                if sent != stub.key:
                    text = "invalid key " + (sent or "") if stub.echo else "invalid key"
                    self.reply(401, {"error": {"message": text}})
                    return
                parts = urlsplit(self.path)
                pairs = parse_qsl(parts.query, keep_blank_values=True)
                status, body, *extra = stub.source.respond(parts.path, pairs)
                if status == 200:
                    stub.responses.append(body)
                self.reply(status, body, extra[0] if extra else {})

            def reply(self, status, body, headers=None):
                time.sleep(stub.delay)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    for name, value in (headers or {}).items():
                        self.send_header(name, value)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join()


def strings_in(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings_in(value)


class Canned:
    """A source that answers every request the same way."""

    def __init__(self, status, body, headers=None):
        self.answer = (status, body, headers or {})

    def respond(self, path, params):
        return self.answer
