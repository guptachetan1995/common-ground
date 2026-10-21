"""The two hosts' files against the server they start: the boot script for EC2, the Render form in the
deploy guide, and the settings both lean on. Everything is read from the files themselves, so a change to the
server or to a file that breaks the other fails here. Only loopback is used; no host is contacted."""
import http.client
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from common_ground import __main__ as cli
from common_ground import settings, web
from tests.served import Browser, Served

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "deploy", "ec2", "user-data.sh")
GUIDE = os.path.join(ROOT, "docs", "deploy.md")
PUBLIC_NAME = "203-0-113-9.nip.io"
USER_DATA_LIMIT = 16 * 1024


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def script_value(name):
    found = re.search(rf"^{name}=(\S*)", read(SCRIPT), re.M)
    assert found, name
    return found.group(1)


def heredoc(name):
    found = re.search(rf"<<'?{name}'?\n(.*?)\n{name}\n", read(SCRIPT), re.S)
    assert found, name
    return found.group(1)


def first_code(cell):
    found = re.search(r"`([^`]*)`", cell)
    return found.group(1) if found else ""


def table_under(heading, first_header):
    """The first table after a heading: (first cell, second cell, whole row), backticks kept."""
    lines = read(GUIDE).splitlines()
    start = lines.index(heading)
    at = next(i for i in range(start, len(lines)) if lines[i].startswith(f"| {first_header} |"))
    rows = []
    for line in lines[at + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        rows.append((first_code(cells[0]) or cells[0], cells[1], line))
    return rows


def render_form():
    return {name: value for name, value, _ in table_under("### Every field of the creation form", "Field")}


def render_variables():
    return {name: value for name, value, _ in table_under("### Every field of the creation form", "Key")}


def script_env(provider="fake", host=PUBLIC_NAME):
    """The environment file the boot script writes, rebuilt from its own printf lines."""
    known = {"PROVIDER": provider, "APP_PORT": script_value("APP_PORT"), "HOST": host,
             "DAILY_LIVE_CALLS": script_value("DAILY_LIVE_CALLS"), "QLOO_API_KEY": "k"}
    env = {}
    for match in re.finditer(r"printf '([A-Z_]+)=(%s|[^%\\']*)\\n'(?: \"\$([A-Z_]+)\")?", read(SCRIPT)):
        name, literal, variable = match.groups()
        env[name] = known[variable] if variable else literal
    if provider != "live":
        env.pop("QLOO_API_KEY", None)
    return env


class BootScript(unittest.TestCase):
    def test_it_is_valid_bash_and_fits_the_user_data_limit(self):
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("no bash on this machine")
        done = subprocess.run([bash, "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertLess(os.path.getsize(SCRIPT), USER_DATA_LIMIT)
        self.assertTrue(read(SCRIPT).startswith("#!/bin/bash\n"))
        self.assertIn("\nset -euo pipefail\n", read(SCRIPT))

    def test_the_key_line_is_empty_marked_and_the_only_one(self):
        lines = [l for l in read(SCRIPT).splitlines() if re.match(r"^QLOO_API_KEY=", l)]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^QLOO_API_KEY=\s+# <<< the one line to edit")
        self.assertEqual(script_value("QLOO_API_KEY"), "")

    def test_no_key_shaped_string_is_in_either_file(self):
        pinned = script_value("CADDY_SHA512")
        for path in (SCRIPT, GUIDE):
            text = read(path).replace(pinned, "").replace("X-aws-ec2-metadata-token-ttl-seconds", "")
            self.assertEqual(re.findall(r"[A-Za-z0-9_-]{32,}", text), [], path)

    def test_the_default_serves_the_sample_source_and_needs_no_key(self):
        self.assertEqual(script_value("PROVIDER"), "fake")
        self.assertNotIn("QLOO_API_KEY", script_env("fake"))
        self.assertEqual(script_env("live")["QLOO_API_KEY"], "k")

    def test_python_is_the_version_the_repository_pins_and_is_called_by_path(self):
        self.assertEqual(read(os.path.join(ROOT, ".python-version")).strip(), "3.13")
        self.assertEqual(script_value("PYTHON"), "/usr/bin/python3.13")
        self.assertRegex(read(SCRIPT), r"dnf install -y tar gzip python3\.13 ")
        self.assertIn("ExecStart=$PYTHON -m common_ground serve", read(SCRIPT))
        self.assertNotIn("python3 -m", read(SCRIPT).replace("python3.13", ""))

    def test_caddy_is_pinned_with_a_sha512_and_the_guide_names_the_same_version(self):
        self.assertRegex(script_value("CADDY_SHA512"), r"^[0-9a-f]{128}$")
        version = script_value("CADDY_VERSION")
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        asset = "releases/download/v$CADDY_VERSION/caddy_${CADDY_VERSION}_linux_amd64.tar.gz"
        self.assertIn(asset, read(SCRIPT))
        self.assertIn("sha512sum -c", read(SCRIPT))
        self.assertIn(f"Caddy {version}", read(GUIDE))
        self.assertIn(f"v{version}", read(GUIDE))

    def test_the_certificate_wait_checks_a_real_certificate_and_logs_its_time(self):
        text = read(SCRIPT)
        self.assertIn('--resolve "$HOST:443:127.0.0.1" "https://$HOST/healthz"', text)
        self.assertNotRegex(text, r"curl[^\n]* (-k|--insecure)")
        self.assertIn("Certificate ready after $SECONDS seconds", text)
        self.assertIn("No certificate after $SECONDS seconds", text)
        self.assertIn("date -u +%H:%M:%S", text)
        self.assertIn("> /dev/console", text)
        self.assertEqual(read(SCRIPT).count("StandardOutput=journal+console"), 2)

    def test_the_key_is_written_only_to_a_root_only_file_and_only_for_live(self):
        text = read(SCRIPT)
        uses = [l for l in text.splitlines() if "$QLOO_API_KEY" in l and "QLOO_API_KEY=" not in l[:13]]
        self.assertEqual([l for l in uses if "printf" in l or "echo" in l or "note " in l], [
            '      if [ "$PROVIDER" = live ]; then printf \'QLOO_API_KEY=%s\\n\' "$QLOO_API_KEY"; fi'])
        self.assertRegex(text, r"\( umask 077\n")
        self.assertIn("> /etc/common-ground.env )", text)
        self.assertNotIn("set -x", text)


class BootScriptAgainstTheServer(unittest.TestCase):
    def setUp(self):
        self.env = script_env("fake")
        with tempfile.TemporaryDirectory() as empty:
            self.config = settings.load(dict(self.env), empty)

    def test_the_settings_it_writes_are_ones_the_server_reads_and_make_it_start(self):
        source = read(os.path.join(ROOT, "common_ground", "settings.py"))
        for name in self.env:
            self.assertIn(f'"{name}"', source, name)
        settings.require_servable(self.config)
        self.assertEqual(self.config.provider, "fake")
        self.assertIn(PUBLIC_NAME, self.config.allowed_hosts)
        self.assertTrue(self.config.trust_proxy)
        self.assertEqual(self.config.daily_live_calls, 300)

    def test_it_binds_loopback_on_the_port_caddy_forwards_to(self):
        self.assertIn(self.config.bind, settings.LOOPBACK_BINDS)
        self.assertEqual(self.config.port, int(script_value("APP_PORT")))
        self.assertEqual(self.config.port, settings.DEFAULT_PORT)
        self.assertNotIn("PORT", self.env)
        site = heredoc("CADDYFILE").replace("$HOST", PUBLIC_NAME).replace("$APP_PORT", str(self.config.port))
        self.assertEqual(re.findall(r"reverse_proxy (\S+)", site), [f"127.0.0.1:{self.config.port}"])

    def test_the_caddyfile_keeps_the_host_and_sets_a_length_the_server_accepts(self):
        site = heredoc("CADDYFILE").replace("$HOST", PUBLIC_NAME).replace("$APP_PORT", str(self.config.port))
        self.assertEqual(site.count("{"), site.count("}"))
        self.assertEqual(re.findall(r"^(\S+) \{$", site, re.M), [PUBLIC_NAME])
        self.assertNotIn("header_up", site)
        self.assertNotIn("tls ", site)
        self.assertNotIn("http://", site)
        buffered = re.search(r"request_buffers (\d+)KB", site)
        self.assertIsNotNone(buffered)
        self.assertLessEqual(int(buffered.group(1)) * 1000, web.MAX_BODY)

    def test_the_two_units_run_unprivileged_and_agree_with_the_files_the_script_writes(self):
        text = read(SCRIPT)
        app = text.split("<<UNIT\n")[1].split("\nUNIT\n")[0]
        caddy = text.split("<<'UNIT'\n")[1].split("\nUNIT\n")[0]
        self.assertIn("User=commonground", app)
        self.assertIn("User=caddy", caddy)
        self.assertIn("EnvironmentFile=/etc/common-ground.env", app)
        self.assertIn("> /etc/common-ground.env )", text)
        self.assertIn("--config /etc/caddy/Caddyfile", caddy)
        self.assertIn("cat > /etc/caddy/Caddyfile", text)
        self.assertIn("AmbientCapabilities=CAP_NET_BIND_SERVICE", caddy)
        self.assertNotIn("User=root", app + caddy)
        self.assertEqual(cli._parser().parse_args(["serve"]).command, "serve")

    def test_a_request_shaped_like_the_one_caddy_forwards_is_a_person_with_a_forwarded_client(self):
        served = Served(allowed_hosts=self.config.allowed_hosts, trust_proxy=self.config.trust_proxy)
        with served:
            browser = Browser(served, host=PUBLIC_NAME, origin=f"https://{PUBLIC_NAME}")
            opened = browser.open("/")
            self.assertEqual(opened.status, 200)
            self.assertTrue(opened.headers["set-cookie"].endswith("; Secure"))
            state = browser.get("/api/state", **{"X-Forwarded-For": "198.51.100.7, 203.0.113.50"}).json
            self.assertEqual((state["actor"], state["actorWhy"], state["limiterKey"]),
                             ("person", "same_origin", "forwarded"))
            args = browser.get("/api/sample").json["args"]
            self.assertTrue(browser.ok("open_outing", args)["outingId"])
            foreign = served.call("GET", "/", host="elsewhere.example")
            self.assertEqual((foreign.status, foreign.json["outcome"]), (403, "bad_host"))


class BootScriptStopsBeforeInstalling(unittest.TestCase):
    """The script runs as root on a real instance, so here it runs against stubs that record being called."""

    COMMANDS = ("dnf", "curl", "useradd", "systemctl", "install", "tar", "sha512sum", "chmod", "rm", "cat",
                "seq", "sleep", "mkdir", "touch")

    def setUp(self):
        if shutil.which("bash") is None:
            self.skipTest("no bash on this machine")
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.calls = os.path.join(self.dir, "calls")
        bin_dir = os.path.join(self.dir, "bin")
        os.mkdir(bin_dir)
        for name in self.COMMANDS:
            path = os.path.join(bin_dir, name)
            with open(path, "w") as fh:
                fh.write(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\nexit 1\n')
            os.chmod(path, 0o755)
        self.bin = bin_dir

    def run_script(self, **lines):
        text = read(SCRIPT)
        for name, value in lines.items():
            text, n = re.subn(rf"^{name}=\S*", lambda m: f"{name}={value}", text, flags=re.M, count=1)
            self.assertEqual(n, 1, name)
        path = os.path.join(self.dir, "script.sh")
        with open(path, "w") as fh:
            fh.write(text)
        done = subprocess.run(
            [shutil.which("bash"), path], capture_output=True, text=True, timeout=30,
            env={"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": self.dir},
        )
        called = read(self.calls).splitlines() if os.path.exists(self.calls) else []
        return done.returncode, done.stdout + done.stderr, called

    def test_live_with_an_empty_key_line_stops_before_anything_is_installed(self):
        code, said, called = self.run_script(PROVIDER="live")
        self.assertEqual((code, called), (1, []))
        self.assertIn("Nothing was installed", said)
        self.assertIn("QLOO_API_KEY line is empty", said)

    def test_a_key_with_a_quote_a_backslash_or_a_space_is_refused_and_never_echoed(self):
        marker = "K" + secrets.token_hex(8)
        for key in (f"'{marker}\"x'", f"'{marker}\\\\x'", f"'{marker} x'"):
            with self.subTest(key):
                code, said, called = self.run_script(PROVIDER="live", QLOO_API_KEY=key)
                self.assertEqual((code, called), (1, []))
                self.assertIn("Nothing was installed", said)
                self.assertNotIn(marker, said)

    def test_an_unknown_provider_stops_too(self):
        code, said, called = self.run_script(PROVIDER="staging")
        self.assertEqual((code, called), (1, []))
        self.assertIn("PROVIDER must be live or fake", said)

    def test_the_sample_default_goes_on_to_python_first_and_touches_nothing_else_when_dnf_fails(self):
        code, said, called = self.run_script()
        self.assertEqual(code, 1)
        self.assertEqual(called, ["dnf install -y tar gzip python3.13"])
        self.assertIn("Settings accepted (provider fake)", said)
        self.assertIn("Nothing else was installed", said)

    def test_a_key_typed_with_the_sample_provider_is_ignored_and_the_script_says_so_without_the_key(self):
        key = "typed" + "x" * 20
        code, said, called = self.run_script(QLOO_API_KEY=key)
        self.assertEqual(code, 1)
        self.assertIn("the key is ignored and is not copied onto this instance", said)
        self.assertNotIn(key, said)


class RenderForm(unittest.TestCase):
    def test_the_start_command_runs_the_serve_command_the_server_has(self):
        command = first_code(render_form()["Start Command"])
        self.assertTrue(command.startswith("python -m common_ground "), command)
        argv = command[len("python -m common_ground "):].split()
        self.assertEqual(cli._parser().parse_args(argv).command, "serve")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "common_ground", "__main__.py")))
        self.assertIn("python3 -m common_ground serve", read(GUIDE))

    def test_the_plain_fields_are_the_ones_the_plan_and_render_call_for(self):
        form = render_form()
        self.assertEqual(first_code(form["Build Command"]), "true")
        self.assertEqual(first_code(form["Language"]), "Python 3")
        self.assertEqual(first_code(form["Branch"]), "main")
        self.assertEqual(first_code(form["Compute plan"]), "Free")
        self.assertEqual(first_code(form["Repository"]), "guptachetan1995/common-ground")
        self.assertEqual(form["Root Directory"], "empty")
        self.assertTrue(form["Auto-Deploy (Settings page)"].startswith("`On Commit`"))

    def test_no_blueprint_ships_unless_it_names_the_free_plan(self):
        paths = [os.path.join(ROOT, name) for name in ("render.yaml", "render.yml")]
        for path in [p for p in paths if os.path.exists(p)]:
            self.assertRegex(read(path), r"(?m)^\s*plan:\s*free\s*$", path)

    def test_the_health_check_path_is_the_one_the_server_answers_for_any_host(self):
        path = first_code(render_form()["Health Check Path (under Advanced)"])
        self.assertEqual(path, "/healthz")
        self.assertIn('GET /healthz`', read(GUIDE))
        with Served() as served:
            for host in (None, "elsewhere.example"):
                answer = served.call("GET", path, host=host)
                self.assertEqual((answer.status, answer.text), (200, "ok\n"))
            self.assertEqual(served.call("HEAD", path).status, 200)

    def test_the_variables_are_ones_the_server_reads_and_with_render_s_hostname_it_starts(self):
        variables = {name: first_code(value) for name, value in render_variables().items()}
        source = read(os.path.join(ROOT, "common_ground", "settings.py"))
        for name in variables:
            self.assertIn(f'"{name}"', source, name)
        self.assertNotIn("COMMON_GROUND_ALLOWED_HOSTS", variables)
        self.assertTrue(render_variables()["QLOO_API_KEY"].startswith("you paste it"))
        skipped = ("COMMON_GROUND_PROVIDER", "QLOO_API_KEY")
        env = {k: v for k, v in variables.items() if v and k not in skipped}
        env["COMMON_GROUND_PROVIDER"] = "fake"
        with tempfile.TemporaryDirectory() as empty:
            config = settings.load({**env, "RENDER_EXTERNAL_HOSTNAME": "common-ground.onrender.com",
                                    "COMMON_GROUND_PORT": "8761"}, empty)
            settings.require_servable(config)
            self.assertEqual((config.port, config.bind, config.trust_proxy), (10000, "0.0.0.0", True))
            self.assertIn("common-ground.onrender.com", config.allowed_hosts)
            with self.assertRaises(settings.SettingsError) as caught:
                settings.require_servable(settings.load(env, empty))
        self.assertEqual(caught.exception.setting, "COMMON_GROUND_ALLOWED_HOSTS")

    def test_the_guide_never_puts_a_key_value_in_a_variable_row_and_says_when_each_provider_applies(self):
        for _, value, _ in table_under("### Every field of the creation form", "Key"):
            self.assertNotRegex(value, r"[A-Za-z0-9_-]{20,}")
        text = read(GUIDE)
        for phrase in ("`fake`", "`live`", "Create Web Service", "21 Oct 2026", "shapes_unverified",
                       "## What no one could check without an account",
                       "Until the probe has run, deploy with `fake`"):
            self.assertIn(phrase, text)


class StartCommandEndToEnd(unittest.TestCase):
    """The Render start command with Render's own PORT, for real: the program must listen where PORT says."""

    def free_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def test_the_port_a_host_injects_is_the_port_it_listens_on_and_the_allowed_host_is_honoured(self):
        port = self.free_port()
        with tempfile.TemporaryDirectory() as cwd:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.path.abspath(ROOT),
                   "PORT": str(port), "COMMON_GROUND_PORT": str(self.free_port()),
                   "COMMON_GROUND_BIND": "127.0.0.1", "COMMON_GROUND_PROVIDER": "fake",
                   "COMMON_GROUND_ALLOWED_HOSTS": "demo.example", "COMMON_GROUND_TRUST_PROXY": "1"}
            process = subprocess.Popen(
                [sys.executable, "-m", "common_ground", "serve"], cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.addCleanup(lambda: (process.stdout.close(), process.stderr.close()))
            self.addCleanup(process.wait)
            self.addCleanup(process.terminate)
            answer = self.wait_for(port)
            self.assertEqual(answer, (200, b"ok\n"))
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/", headers={"Host": "demo.example", "Sec-Fetch-Site": "none"})
            page = connection.getresponse()
            page.read()
            self.assertEqual(page.status, 200)
            self.assertTrue(page.getheader("Set-Cookie").endswith("; Secure"))
            connection.close()

    def wait_for(self, port):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                connection.request("GET", "/healthz", headers={"Host": "anything.example"})
                reply = connection.getresponse()
                return reply.status, reply.read()
            except OSError:
                time.sleep(0.1)
        self.fail("the server did not start")


if __name__ == "__main__":
    unittest.main()
