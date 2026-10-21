"""A rig for looking at the page in a real browser, never run by the tests.

Run it as `python3 -m tests.browser_rig CASE`.

It serves the real web layer on loopback around a source a case chooses, so a state the plain `serve`
command cannot reach (a ceiling spent, a Qloo error, no place shared by everyone) is on screen. Importing
this package blocks every connection beyond loopback, so nothing here can reach Qloo, and the key it hands
the live source is made up on the spot.

`proxy` in front of a case adds a loopback reverse proxy on a second port that strips the browser's
`Sec-Fetch-*` labels, which is what a browser that sends none looks like to the server.
"""
import argparse
import dataclasses
import http.client
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common_ground import measured, settings, sources, web
from common_ground.gateway import Gateway
from tests.session import ScriptedSource, Transport, forward, reverse, slice_of
from tests.support import fake_key

HOP_BY_HOP = ("connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-connection", "te",
              "trailer")
CASES = {}


def case(function):
    CASES[function.__name__] = function
    return function


def config(**changes):
    return settings.Settings(**{"provider": "fake", **changes})


def gateway(source, sample=None, **changes):
    return Gateway(source, config(**changes), sample=sample)


@case
def sample():
    return gateway(sources.FakeSource())


@case
def none_shared():
    taste = {"lost in translation": forward, "the bear": reverse, "patagonia": forward,
             "katz's delicatessen": reverse}
    return gateway(ScriptedSource(taste, with_explainability=False))


@case
def none_close():
    taste = {"lost in translation": slice_of(0, 4), "the bear": slice_of(1, 4), "patagonia": slice_of(2, 4),
             "katz's delicatessen": slice_of(3, 4)}
    return gateway(ScriptedSource(taste, group_size=12, with_explainability=False))


@case
def thin_list():
    return gateway(ScriptedSource({}, group_size=4))


@case
def no_explainability():
    return gateway(sources.FakeSource(with_explainability=False, with_affinity=False))


@case
def nothing_known():
    from tests.test_searched_marks import Silent
    return gateway(Silent())


@case
def small_limit():
    return gateway(sources.FakeSource(), call_limit=11)


def live(ceiling, transport=None, sample_too=True):
    measured.UNVERIFIED = frozenset()
    key = fake_key()
    stand_in = transport or Transport()
    source = sources.LiveSource(key, daily_ceiling=ceiling, cache_ttl_s=3600, send=stand_in)
    return gateway(source, sample=sources.FakeSource() if sample_too else None, provider="live", api_key=key)


@case
def ceiling_soon():
    return live(ceiling=12)


@case
def ceiling_spent():
    return live(ceiling=1)


@case
def qloo_down():
    return live(ceiling=300, transport=Transport(fail_when=lambda request: request.path == "/v2/insights"))


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    upstream = ("127.0.0.1", 0)

    def log_message(self, *args):
        pass

    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        sent = {name: value for name, value in self.headers.items()
                if not name.lower().startswith("sec-fetch-") and name.lower() not in HOP_BY_HOP}
        link = http.client.HTTPConnection(*self.upstream, timeout=30)
        try:
            link.request(self.command, self.path, body=body or None, headers=sent)
            answer = link.getresponse()
            data = answer.read()
            self.send_response(answer.status)
            for name, value in answer.getheaders():
                if name.lower() not in HOP_BY_HOP + ("content-length",):
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            link.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = forward


def start_proxy(upstream_port, port=0):
    handler = type("Bound", (Proxy,), {"upstream": ("127.0.0.1", upstream_port)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m tests.browser_rig")
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--proxy-port", type=int, default=0,
                        help="also listen here, with the browser's Sec-Fetch-* labels stripped")
    parser.add_argument("--host", action="append", default=[],
                        help="an extra Host the server answers to, for a name such as cg.localhost")
    args = parser.parse_args(argv)
    built = CASES[args.case]()
    if args.host:
        built.config = dataclasses.replace(
            built.config, allowed_hosts=built.config.allowed_hosts + tuple(args.host))
    server = web.make_server(web.App(built), "127.0.0.1", args.port)
    sys.stdout.write(f"{args.case}: http://127.0.0.1:{server.server_address[1]}/\n")
    if args.proxy_port:
        proxy = start_proxy(server.server_address[1], args.proxy_port)
        sys.stdout.write(f"labels stripped: http://127.0.0.1:{proxy.server_address[1]}/\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
