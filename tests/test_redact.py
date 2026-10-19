from obsergent.proxy.redact import redact, safe_command, to_attr


def test_secret_keys_are_hidden_even_when_nested():
    out = redact({"query": "python", "api_key": "abc", "nested": {"Password": "p", "ok": 1}, "list": [{"token": "t"}]})
    assert out == {"query": "python", "api_key": "***", "nested": {"Password": "***", "ok": 1},
                   "list": [{"token": "***"}]}


def test_secret_looking_values_are_masked():
    out = redact({"note": "key sk-abcdefghijklmnopqrstuv, mail bob@example.com, card 4111 1111 1111 1111"})
    assert "sk-" not in out["note"] and "@" not in out["note"] and "4111" not in out["note"]


def test_to_attr_sorts_keys_and_truncates():
    assert to_attr({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'  # same arguments -> same text (replay needs this)
    assert to_attr("x" * 100, limit=10).endswith("...(truncated)")


def test_safe_command_hides_secret_flags():
    cmd = ["npx", "server", "--api-key", "abc123", "--token=zzz", "/tmp"]
    assert safe_command(cmd) == "npx server --api-key *** --token=*** /tmp"
