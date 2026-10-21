"""The only environment reader.

A setting is looked up in the file COMMON_GROUND_ENV_FILE names, then in ./.env, then in the process
environment; an empty value counts as unset. Errors name the setting and never its value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import fair_share

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
LOOPBACK_BINDS = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = 8761
DEFAULT_AGENT_CALLS_PER_DAY = 48
DEFAULT_DAILY_LIVE_CALLS = 300
DEFAULT_CACHE_TTL_S = 86400


class SettingsError(Exception):
    def __init__(self, setting: str, problem: str) -> None:
        super().__init__(f"{setting}: {problem}")
        self.setting = setting


@dataclass(frozen=True)
class Settings:
    api_key: str | None = field(default=None, repr=False)
    provider: str = "fake"
    call_limit: int = fair_share.CALL_LIMIT_DEFAULT
    agent_calls_per_day: int = DEFAULT_AGENT_CALLS_PER_DAY
    daily_live_calls: int = DEFAULT_DAILY_LIVE_CALLS
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S
    bind: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS
    trust_proxy: bool = False

    @property
    def key_status(self) -> str:
        return "set" if self.api_key else "missing"


def _read_env_file(path: str, setting: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        raise SettingsError(setting, "the file cannot be read") from None
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def _integer(raw: str, setting: str, low: int, high: int) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(setting, "must be a whole number") from None
    if not low <= value <= high:
        raise SettingsError(setting, f"must be between {low} and {high}")
    return value


def load(environ: dict[str, str] | None = None, cwd: str = ".") -> Settings:
    environ = os.environ if environ is None else environ
    layers = [dict(environ)]
    dotenv = os.path.join(cwd, ".env")
    if os.path.isfile(dotenv):
        layers.insert(0, _read_env_file(dotenv, ".env"))
    named = [layer["COMMON_GROUND_ENV_FILE"] for layer in layers if layer.get("COMMON_GROUND_ENV_FILE")]
    chosen = named[0] if named else ""
    if chosen:
        layers.insert(0, _read_env_file(chosen, "COMMON_GROUND_ENV_FILE"))

    def get(name: str) -> str:
        return next((layer[name] for layer in layers if layer.get(name)), "")

    key = get("QLOO_API_KEY") or None

    provider = get("COMMON_GROUND_PROVIDER").lower()
    if provider not in ("", "live", "fake"):
        raise SettingsError("COMMON_GROUND_PROVIDER", "must be live or fake")
    if not provider:
        provider = "live" if key else "fake"

    if get("PORT"):
        port = _integer(get("PORT"), "PORT", 0, 65535)
    elif get("COMMON_GROUND_PORT"):
        port = _integer(get("COMMON_GROUND_PORT"), "COMMON_GROUND_PORT", 0, 65535)
    else:
        port = DEFAULT_PORT

    extra = [h.strip().lower() for h in get("COMMON_GROUND_ALLOWED_HOSTS").split(",") if h.strip()]
    render_host = get("RENDER_EXTERNAL_HOSTNAME").strip().lower()
    if render_host:
        extra.append(render_host)

    def number(name: str, default: int, high: int) -> int:
        return _integer(get(name), name, 1, high) if get(name) else default

    return Settings(
        api_key=key,
        provider=provider,
        call_limit=number(
            "COMMON_GROUND_CALL_LIMIT", fair_share.CALL_LIMIT_DEFAULT, fair_share.CALL_LIMIT_MAX
        ),
        agent_calls_per_day=number("COMMON_GROUND_AGENT_CALLS_PER_DAY", DEFAULT_AGENT_CALLS_PER_DAY, 100000),
        daily_live_calls=number("COMMON_GROUND_DAILY_LIVE_CALLS", DEFAULT_DAILY_LIVE_CALLS, 1000000),
        cache_ttl_s=number("COMMON_GROUND_CACHE_TTL_S", DEFAULT_CACHE_TTL_S, 30 * 86400),
        bind=get("COMMON_GROUND_BIND") or "127.0.0.1",
        port=port,
        allowed_hosts=LOOPBACK_HOSTS + tuple(extra),
        trust_proxy=get("COMMON_GROUND_TRUST_PROXY") == "1",
    )


def require_servable(settings: Settings) -> None:
    """A bind beyond this machine needs at least one allowed Host, or the server would answer anyone."""
    if settings.bind not in LOOPBACK_BINDS and settings.allowed_hosts == LOOPBACK_HOSTS:
        raise SettingsError(
            "COMMON_GROUND_ALLOWED_HOSTS", "must name the public host when the bind is not loopback"
        )


def require_key(settings: Settings) -> str:
    if not settings.api_key:
        raise SettingsError("QLOO_API_KEY", "is not set")
    return settings.api_key
