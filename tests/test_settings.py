import dataclasses
import os
import tempfile
import unittest

from common_ground import settings


def write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class Defaults(unittest.TestCase):
    def test_nothing_set(self):
        s = settings.load({}, cwd=tempfile.gettempdir() + "/none-here")
        self.assertEqual(s.port, 8761)
        self.assertEqual(s.bind, "127.0.0.1")
        self.assertEqual(s.provider, "fake")
        self.assertEqual((s.call_limit, s.agent_calls_per_day, s.daily_live_calls), (30, 48, 300))
        self.assertEqual(s.cache_ttl_s, 86400)
        self.assertFalse(s.trust_proxy)
        self.assertEqual(s.key_status, "missing")
        self.assertEqual(s.allowed_hosts, ("127.0.0.1", "localhost", "[::1]"))

    def test_empty_values_mean_default(self):
        s = settings.load({"COMMON_GROUND_PORT": "", "COMMON_GROUND_CALL_LIMIT": "", "QLOO_API_KEY": ""})
        self.assertEqual((s.port, s.call_limit, s.api_key), (8761, 30, None))


class Port(unittest.TestCase):
    def test_host_port_beats_own_port_beats_default(self):
        self.assertEqual(settings.load({"PORT": "10000", "COMMON_GROUND_PORT": "9000"}).port, 10000)
        self.assertEqual(settings.load({"COMMON_GROUND_PORT": "9000"}).port, 9000)
        self.assertEqual(settings.load({}).port, 8761)

    def test_bad_port_names_the_setting(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load({"COMMON_GROUND_PORT": "eighty"})
        self.assertEqual(caught.exception.setting, "COMMON_GROUND_PORT")
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load({"PORT": "70000"})
        self.assertEqual(caught.exception.setting, "PORT")


class Hosts(unittest.TestCase):
    def test_loopback_bind_needs_no_allowed_host(self):
        settings.require_servable(settings.load({"COMMON_GROUND_BIND": "127.0.0.1"}))

    def test_public_bind_with_no_allowed_host_names_the_setting(self):
        s = settings.load({"COMMON_GROUND_BIND": "0.0.0.0"})
        with self.assertRaises(settings.SettingsError) as caught:
            settings.require_servable(s)
        self.assertEqual(caught.exception.setting, "COMMON_GROUND_ALLOWED_HOSTS")

    def test_listed_hosts_and_render_host_are_allowed(self):
        listed = " A.example , b.example,"
        s = settings.load({"COMMON_GROUND_BIND": "0.0.0.0", "COMMON_GROUND_ALLOWED_HOSTS": listed})
        settings.require_servable(s)
        self.assertEqual(s.allowed_hosts[-2:], ("a.example", "b.example"))
        render = settings.load(
            {"COMMON_GROUND_BIND": "0.0.0.0", "RENDER_EXTERNAL_HOSTNAME": "cg.onrender.com"}
        )
        settings.require_servable(render)
        self.assertIn("cg.onrender.com", render.allowed_hosts)

    def test_trust_proxy_only_on_one(self):
        self.assertTrue(settings.load({"COMMON_GROUND_TRUST_PROXY": "1"}).trust_proxy)
        self.assertFalse(settings.load({"COMMON_GROUND_TRUST_PROXY": "true"}).trust_proxy)


class Limits(unittest.TestCase):
    def test_overrides(self):
        s = settings.load({
            "COMMON_GROUND_CALL_LIMIT": "45",
            "COMMON_GROUND_AGENT_CALLS_PER_DAY": "10",
            "COMMON_GROUND_DAILY_LIVE_CALLS": "99",
            "COMMON_GROUND_CACHE_TTL_S": "60",
        })
        self.assertEqual(
            (s.call_limit, s.agent_calls_per_day, s.daily_live_calls, s.cache_ttl_s), (45, 10, 99, 60)
        )

    def test_the_call_limit_cannot_exceed_sixty(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load({"COMMON_GROUND_CALL_LIMIT": "61"})
        self.assertEqual(caught.exception.setting, "COMMON_GROUND_CALL_LIMIT")

    def test_a_provider_must_be_live_or_fake(self):
        with self.assertRaises(settings.SettingsError):
            settings.load({"COMMON_GROUND_PROVIDER": "replay"})

    def test_provider_follows_the_key_unless_stated(self):
        self.assertEqual(settings.load({"QLOO_API_KEY": "k" * 8}).provider, "live")
        stated = settings.load({"QLOO_API_KEY": "k" * 8, "COMMON_GROUND_PROVIDER": "fake"})
        self.assertEqual(stated.provider, "fake")
        self.assertEqual(settings.load({"COMMON_GROUND_PROVIDER": "live"}).provider, "live")


class Layers(unittest.TestCase):
    def test_env_file_over_dotenv_over_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".env", "COMMON_GROUND_PORT=7001\nCOMMON_GROUND_CALL_LIMIT=41\nCOMMON_GROUND_BIND=\n")
            key_file = write(tmp, "elsewhere.env", "COMMON_GROUND_PORT=7002\n")
            env = {
                "COMMON_GROUND_PORT": "7000",
                "COMMON_GROUND_CALL_LIMIT": "40",
                "COMMON_GROUND_BIND": "localhost",
            }
            plain = settings.load(env, cwd=tmp)
            self.assertEqual((plain.port, plain.call_limit, plain.bind), (7001, 41, "localhost"))
            named = settings.load({**env, "COMMON_GROUND_ENV_FILE": key_file}, cwd=tmp)
            self.assertEqual((named.port, named.call_limit), (7002, 41))

    def test_env_file_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "k.env", "# a comment\n\nexport COMMON_GROUND_PORT = '7003'\nnot a setting\n")
            self.assertEqual(settings.load({"COMMON_GROUND_ENV_FILE": path}, cwd=tmp).port, 7003)

    def test_the_file_named_by_a_setting_must_exist(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load({"COMMON_GROUND_ENV_FILE": "/nonexistent/qloo.env"})
        self.assertEqual(caught.exception.setting, "COMMON_GROUND_ENV_FILE")
        self.assertNotIn("nonexistent", str(caught.exception))

    def test_the_file_may_name_itself_through_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = write(tmp, "k.env", "COMMON_GROUND_PORT=7004\n")
            write(tmp, ".env", f"COMMON_GROUND_ENV_FILE={key_file}\n")
            self.assertEqual(settings.load({}, cwd=tmp).port, 7004)


class TheKey(unittest.TestCase):
    key = "key-" + "q" * 24

    def test_key_from_each_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "k.env", "QLOO_API_KEY=" + self.key + "\n")
            self.assertEqual(settings.load({"COMMON_GROUND_ENV_FILE": path}, cwd=tmp).api_key, self.key)
            self.assertEqual(settings.load({"QLOO_API_KEY": self.key}, cwd=tmp).api_key, self.key)

    def test_the_key_is_not_in_repr_or_status(self):
        s = settings.load({"QLOO_API_KEY": self.key})
        self.assertNotIn(self.key, repr(s))
        self.assertNotIn(self.key, str(dataclasses.asdict(dataclasses.replace(s, api_key=None))))
        self.assertEqual(s.key_status, "set")

    def test_errors_never_carry_values(self):
        for env in (
            {"QLOO_API_KEY": self.key, "COMMON_GROUND_PORT": self.key},
            {"QLOO_API_KEY": self.key, "COMMON_GROUND_CALL_LIMIT": self.key},
            {"QLOO_API_KEY": self.key, "COMMON_GROUND_PROVIDER": self.key},
        ):
            with self.assertRaises(settings.SettingsError) as caught:
                settings.load(env)
            self.assertNotIn(self.key, str(caught.exception))

    def test_require_key_names_the_setting(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.require_key(settings.load({}))
        self.assertEqual(caught.exception.setting, "QLOO_API_KEY")
        self.assertEqual(settings.require_key(settings.load({"QLOO_API_KEY": self.key})), self.key)


class NoWorkspaceTimeout(unittest.TestCase):
    def test_no_such_setting(self):
        names = {f.name for f in dataclasses.fields(settings.Settings)}
        self.assertFalse([n for n in names if "workspace" in n or "idle" in n or "timeout" in n])
        with open(settings.__file__, encoding="utf-8") as fh:
            source = fh.read().upper()
        self.assertNotIn("WORKSPACE_TTL", source)
        self.assertNotIn("TIMEOUT", source)


if __name__ == "__main__":
    unittest.main()
