"""config.py: settings come from config.yaml through functions; environment variables win; defaults fill the gaps."""
import pytest

from obsergent import config


@pytest.fixture(autouse=True)
def fresh_config(monkeypatch):
    """Each test starts with no OBSERGENT_* overrides and re-reads the config file afterwards."""
    for variable in set(config.ENVIRONMENT.values()) | {"OBSERGENT_CONFIG"}:
        monkeypatch.delenv(variable, raising=False)
    config.reload()
    yield
    config.reload()


def use_file(monkeypatch, tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    monkeypatch.setenv("OBSERGENT_CONFIG", str(path))
    config.reload()


def test_the_shipped_config_yaml_matches_the_built_in_defaults():
    shipped = config.load()
    assert config.port() == 7318 and config.grpc_port() == 4317 and config.proxy_port() == 7319
    assert shipped == {section: dict(values) for section, values in config.DEFAULTS.items()}


def test_values_come_from_the_yaml_file(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "server:\n  port: 8123\nproxy:\n  port: 8124\nstorage:\n  path: ~/x/y.db\n")
    assert config.port() == 8123 and config.proxy_port() == 8124
    assert config.db_path().name == "y.db" and "~" not in str(config.db_path())
    assert config.endpoint() == "http://127.0.0.1:8123"  # built from host and port


def test_a_key_missing_from_the_file_falls_back_to_the_default(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "server:\n  port: 8123\n")
    assert config.grpc_port() == 4317 and config.mcp_context() == "/bookshop"


def test_environment_variables_win_over_the_file(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "server:\n  port: 8123\n")
    monkeypatch.setenv("OBSERGENT_PORT", "9999")
    assert config.port() == 9999


def test_an_explicit_endpoint_replaces_the_computed_one(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, 'server:\n  endpoint: "http://collector:1234"\n')
    assert config.endpoint() == "http://collector:1234"


def test_gateway_addresses_and_urls(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "gateway:\n  router: http://gw:8080/\n  mcp_context: /shop\n  mcp_name: shop\n")
    assert config.gateway_mcp_url() == "http://gw:8080/shop/mcp"
    assert config.proxy_url() == "http://127.0.0.1:7319/mcp/shop"


def test_the_password_is_only_read_from_the_environment(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "gateway:\n  password: not-read\n")
    assert config.gateway_password() == ""
    monkeypatch.setenv("WSO2AP_GW_PASSWORD", "secret")
    assert config.gateway_password() == "secret"


def test_a_named_file_that_does_not_exist_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSERGENT_CONFIG", str(tmp_path / "missing.yaml"))
    config.reload()
    with pytest.raises(FileNotFoundError):
        config.load()


def test_pricing_settings_have_defaults_and_the_environment_wins(monkeypatch):
    assert config.pricing_enabled() and config.pricing_auto_refresh()
    assert config.pricing_refresh_minutes("openrouter") == 30 and config.pricing_refresh_minutes("litellm") == 120
    assert config.pricing_exact_from_provider() and config.pricing_credits_per_usd() == 1
    assert config.pricing_reprice() == "call_time"
    assert set(config.pricing_sources()) == {"models_dev", "openrouter", "huggingface", "litellm"}
    assert "ollama" in config.pricing_local_providers() and config.pricing_overrides() == {}
    monkeypatch.setenv("OBSERGENT_PRICING_AUTO_REFRESH", "false")
    monkeypatch.setenv("OBSERGENT_PRICING_REPRICE", "NOW")
    monkeypatch.setenv("OBSERGENT_PRICING", "0")
    assert not config.pricing_auto_refresh() and config.pricing_reprice() == "now" and not config.pricing_enabled()


def test_pricing_overrides_come_from_the_file(monkeypatch, tmp_path):
    use_file(monkeypatch, tmp_path, "pricing:\n  overrides:\n    my-model: {input_per_million: 0.5, output_per_million: 1.5}\n")
    assert config.pricing_overrides()["my-model"]["output_per_million"] == 1.5
