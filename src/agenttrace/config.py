"""Settings: read from config.yaml (repository root), with environment variables on top, through functions.

Every other module asks this one for its settings, so there is exactly one place to look when you wonder "where does the
port / database path come from?". Order of precedence, highest first:

    1. an environment variable (for one run:  AGENTTRACE_PORT=7390 agenttrace up)
    2. config.yaml
    3. the built-in default below (so AgentTrace also works with no config file at all)

The functions read the settings each time they are called (the YAML file itself is read once), so changing an
environment variable takes effect immediately.
"""
# os reads environment variables.
import os

# lru_cache remembers the result of reading the YAML file, so it is read only once.
from functools import lru_cache

# Path represents file and folder locations.
from pathlib import Path

# yaml (PyYAML) reads config.yaml.
import yaml

# The repository root: this file is src/agenttrace/config.py, so the root is two folders up.
ROOT = Path(__file__).resolve().parents[2]

# Built-in defaults: the same values config.yaml ships with. A key missing from config.yaml falls back to these.
DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 7318, "grpc_port": 4317, "endpoint": ""},
    "storage": {"path": "~/.agenttrace/agenttrace.db"},
    "recording": {"max_attr_chars": 4000},
    "proxy": {"host": "127.0.0.1", "port": 7319},
    "gateway": {"router": "http://localhost:8080", "controller": "http://localhost:9090/api/management/v1",
                "username": "admin", "mcp_name": "wso2", "mcp_context": "/bookshop"},
    "bookshop": {"http_port": 9100},
    "pricing": {
        "enabled": True, "auto_refresh": True, "reprice": "call_time", "exact_from_provider": True, "credits_per_usd": 1,
        "refresh_minutes": {"openrouter": 30, "huggingface": 30, "models_dev": 120, "litellm": 120},
        "sources": {"models_dev": "https://models.dev/api.json",
                    "openrouter": "https://openrouter.ai/api/v1/models",
                    "huggingface": "https://router.huggingface.co/v1/models",
                    "litellm": "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"},
        "local_providers": ["ollama", "lmstudio", "llamacpp", "vllm"],
        "overrides": {},
    },
}

# Setting (dotted key) -> the environment variable that overrides it.
ENVIRONMENT = {
    "server.host": "AGENTTRACE_HOST",
    "server.port": "AGENTTRACE_PORT",
    "server.grpc_port": "AGENTTRACE_GRPC_PORT",
    "server.endpoint": "AGENTTRACE_ENDPOINT",
    "storage.path": "AGENTTRACE_DB",
    "recording.max_attr_chars": "AGENTTRACE_MAX_ATTR_CHARS",
    "proxy.port": "AGENTTRACE_PROXY_PORT",
    "gateway.router": "GATEWAY_ROUTER",
    "gateway.controller": "GATEWAY_CONTROLLER",
    "gateway.username": "WSO2AP_GW_USERNAME",
    "bookshop.http_port": "BOOKSHOP_PORT",
    "pricing.enabled": "AGENTTRACE_PRICING",
    "pricing.auto_refresh": "AGENTTRACE_PRICING_AUTO_REFRESH",
    "pricing.exact_from_provider": "AGENTTRACE_PRICING_EXACT",
    "pricing.reprice": "AGENTTRACE_PRICING_REPRICE",
}


def config_file() -> Path | None:
    """The config.yaml in use: $AGENTTRACE_CONFIG, else ./config.yaml, else the repository's; None if there is none."""
    # An explicit path wins.
    explicit = os.environ.get("AGENTTRACE_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    # Otherwise the first config.yaml found in the current folder, then in the repository root.
    for candidate in (Path.cwd() / "config.yaml", ROOT / "config.yaml"):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def load() -> dict:
    """The whole configuration: the defaults, overlaid with the values in config.yaml."""
    # Start from a copy of the defaults.
    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    path = config_file()
    if path is None:
        return merged
    # An explicitly named file that is missing is a mistake worth reporting.
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    # safe_load turns the YAML text into dicts; an empty file gives None.
    for section, values in (yaml.safe_load(path.read_text()) or {}).items():
        # Overlay the file's values on the defaults of that section.
        merged.setdefault(section, {}).update(values or {})
    return merged


def reload() -> None:
    """Forget the cached file, so the next call reads config.yaml again (used by tests)."""
    load.cache_clear()


def get(key: str, default=None):
    """One setting by its dotted key, e.g. get("server.port"): the environment variable, else config.yaml, else default."""
    # 1. the environment variable that belongs to this key.
    variable = ENVIRONMENT.get(key)
    if variable and os.environ.get(variable) not in (None, ""):
        return os.environ[variable]
    # 2. the YAML value (or the built-in default): walk down "section.name".
    section, _, name = key.partition(".")
    value = load().get(section, {}).get(name)
    return default if value is None else value


# ------------------------------------------------------------------------------------------------ the server
def host() -> str:
    """Address the AgentTrace server listens on (127.0.0.1 = this machine only)."""
    return str(get("server.host"))


def port() -> int:
    """Port of the web UI, the REST API and the OTLP/HTTP receiver."""
    # Environment variables are text, so int(...) turns "7318" into the number 7318.
    return int(get("server.port"))


def grpc_port() -> int:
    """Port of the OTLP/gRPC receiver (`agenttrace up --grpc`)."""
    return int(get("server.grpc_port"))


def endpoint() -> str:
    """Where SDKs and proxies send their spans: the server's address unless config says otherwise."""
    return str(get("server.endpoint") or f"http://{host()}:{port()}")


def db_path() -> Path:
    """The SQLite file that stores everything (~ is expanded to your home folder)."""
    return Path(str(get("storage.path"))).expanduser()


def max_attr_chars() -> int:
    """Longest text kept in one span attribute (arguments, results...); longer values are cut."""
    return int(get("recording.max_attr_chars"))


# ------------------------------------------------------------------------------------------- the HTTP proxy
def proxy_host() -> str:
    """Address `agenttrace proxy-http` listens on."""
    return str(get("proxy.host"))


def proxy_port() -> int:
    """Port of `agenttrace proxy-http`."""
    return int(get("proxy.port"))


def proxy_url() -> str:
    """The MCP address clients use to go through the recording proxy to the gateway."""
    return f"http://{proxy_host()}:{proxy_port()}/mcp/{mcp_name()}"


# ------------------------------------------------------------------------------------- the WSO2 gateway
def gateway_router() -> str:
    """Where MCP traffic enters the gateway."""
    return str(get("gateway.router")).rstrip("/")


def gateway_controller() -> str:
    """The gateway controller's management API (where MCP servers are registered)."""
    return str(get("gateway.controller")).rstrip("/")


def gateway_username() -> str:
    """The gateway admin user name."""
    return str(get("gateway.username"))


def gateway_password() -> str:
    """The gateway admin password: only from the environment (WSO2AP_GW_PASSWORD), never from a file."""
    return os.environ.get("WSO2AP_GW_PASSWORD", "")


def mcp_name() -> str:
    """The MCP server's name in AgentTrace (the proxy URL ends with it)."""
    return str(get("gateway.mcp_name"))


def mcp_context() -> str:
    """The MCP server's path in the gateway."""
    return str(get("gateway.mcp_context"))


def gateway_mcp_url() -> str:
    """The MCP server's address at the gateway: <router><context>/mcp."""
    return f"{gateway_router()}{mcp_context()}/mcp"


# ------------------------------------------------------------------------------------------ the example
def bookshop_http_port() -> int:
    """Port of the example MCP server over HTTP."""
    return int(get("bookshop.http_port"))


# ------------------------------------------------------------------------------------------------ pricing
def as_bool(value) -> bool:
    """YAML gives True/False; an environment variable gives text such as "false" or "0"."""
    return value if isinstance(value, bool) else str(value).strip().lower() not in ("false", "0", "no", "off", "")


def pricing_enabled() -> bool:
    """Whether costs are calculated at all."""
    return as_bool(get("pricing.enabled"))


def pricing_auto_refresh() -> bool:
    """Whether prices are downloaded automatically (the one outbound call AgentTrace makes)."""
    return as_bool(get("pricing.auto_refresh"))


def pricing_refresh_minutes(source: str) -> float:
    """How often one price list is checked for changes (minutes); the live lists more often than the community ones."""
    minutes = get("pricing.refresh_minutes") or {}
    return float(minutes.get(source, 120))


def pricing_exact_from_provider() -> bool:
    """Whether the cost a provider reports with each response (OpenRouter, xAI) replaces the estimate."""
    return as_bool(get("pricing.exact_from_provider"))


def pricing_credits_per_usd() -> float:
    """OpenRouter reports credits; how many credits make one US dollar (1)."""
    return float(get("pricing.credits_per_usd"))


def pricing_reprice() -> str:
    """"call_time" = price each call with the price valid when it was made; "now" = with today's price."""
    return "now" if str(get("pricing.reprice")).strip().lower() == "now" else "call_time"


def pricing_sources() -> dict:
    """Name -> URL of each public price list."""
    return dict(get("pricing.sources"))


def pricing_local_providers() -> list[str]:
    """Providers that run on your own machine: they cost nothing per token."""
    return [str(name).lower() for name in get("pricing.local_providers")]


def pricing_overrides() -> dict:
    """Optional prices typed by hand: model -> {input_per_million, output_per_million, ...}. Normally empty."""
    return dict(get("pricing.overrides") or {})
