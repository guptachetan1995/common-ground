"""Shared scaffolding for tests that go over a socket: a real server on a loopback port 0 around a session's
gateway, a client that sends exactly the headers it is given, and a browser stand-in that sends what the
page's own script sends (the workspace cookie, the same-origin label, the origin)."""
import http.client
import json
import threading
from dataclasses import dataclass

from common_ground import outings, web
from tests.session import Session

SAMPLE = "/api/sample"


@dataclass
class Reply:
    status: int
    headers: dict
    body: bytes

    @property
    def json(self):
        return json.loads(self.body)

    @property
    def text(self):
        return self.body.decode("utf-8")


class Served:
    def __init__(self, session=None, max_threads=web.MAX_HANDLER_THREADS, **config):
        self.session = session or Session(**config)
        self.app = web.App(self.session.gateway)
        self.server = web.make_server(self.app, "127.0.0.1", 0, max_threads)
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.origin = f"http://{self.host}"
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

    def call(self, method, path, body=None, headers=None, raw=None, host=None):
        sent = {"Host": self.host if host is None else host, **(headers or {})}
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        if data is not None:
            sent.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body=data, headers=sent)
            answer = connection.getresponse()
            return Reply(answer.status, {k.lower(): v for k, v in answer.getheaders()}, answer.read())
        finally:
            connection.close()


class Browser:
    """One visitor. `labelled=False` is a browser that sends no Sec-Fetch-Site."""

    def __init__(self, served, labelled=True, host=None, origin=None):
        self.served, self.labelled = served, labelled
        self.host = host
        self.origin = origin or served.origin
        self.cookie = None

    def open(self, path="/"):
        reply = self.served.call("GET", path, headers={"Sec-Fetch-Site": "none"} if self.labelled else {},
                                 host=self.host)
        header = reply.headers.get("set-cookie")
        if header:
            self.cookie = header.split(";")[0]
        return reply

    def _headers(self, post, extra):
        sent = {"Cookie": self.cookie} if self.cookie else {}
        if self.labelled:
            sent["Sec-Fetch-Site"] = "same-origin"
        if post:
            sent["Origin"] = self.origin
        return {**sent, **extra}

    def get(self, path, **extra):
        return self.served.call("GET", path, headers=self._headers(False, extra), host=self.host)

    def post(self, path, body, **extra):
        return self.served.call("POST", path, body, headers=self._headers(True, extra), host=self.host)

    @property
    def workspace(self):
        """The document's own record of this visitor's workspace."""
        return outings.workspace(self.served.session.gateway.document, self.cookie.split("=", 1)[1])

    def state(self):
        reply = self.get("/api/state")
        assert reply.status == 200, reply.text
        return reply.json

    def act(self, tool, args=None, **extra):
        reply = self.post("/api/dispatch", {"tool": tool, "args": args}, **extra)
        assert reply.status == 200, (reply.status, reply.text)
        return reply.json

    def ok(self, tool, args=None):
        answer = self.act(tool, args)
        assert answer["ok"], answer
        return answer["result"]


def sample_walk(browser, resolve=True, compare=True):
    """The calls the page's own script makes for "Try the sample group", then the person's clicks: the
    sample's arguments, one search per favourite, the kind word, each person's matches, the kind chosen,
    the comparison. Returns the outing id."""
    browser.open()
    args = browser.get(SAMPLE).json["args"]
    opened = browser.ok("open_outing", args)
    outing_id = opened["outingId"]
    state = browser.state()["outings"][-1]
    for member in state["members"]:
        for favourite in member["favourites"]:
            browser.ok("look_up_favourite", {
                "outing_id": outing_id, "member_id": member["id"], "favourite_id": favourite["id"]})
    tags = browser.ok("look_up_kind", {"outing_id": outing_id, "query": args["kind_query"]})["tags"]
    if resolve:
        state = browser.state()["outings"][-1]
        for member in state["members"]:
            for favourite in member["favourites"]:
                browser.ok("resolve_match", {
                    "outing_id": outing_id, "member_id": member["id"], "favourite_id": favourite["id"],
                    "entity_id": favourite["candidates"][0]["entityId"]})
        browser.ok("change_conditions", {"outing_id": outing_id, "kind_tag": tags[0]["id"]})
        if compare:
            browser.ok("run_comparison", {"outing_id": outing_id})
    return outing_id
