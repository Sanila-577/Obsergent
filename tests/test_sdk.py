"""SDK helpers: framework hooks, optional extras and the context tagging helper."""
import types

import pytest
from opentelemetry.sdk.trace import TracerProvider

from agenttrace.sdk import setup


def test_unknown_framework_is_rejected():
    with pytest.raises(ValueError, match="unknown framework"):
        setup.instrument_framework("cobol", TracerProvider(), required=True)


def test_missing_extra_is_an_error_only_when_requested(monkeypatch):
    monkeypatch.setitem(setup.INSTRUMENTORS, "ghost", ("module_that_does_not_exist", "GhostInstrumentor"))
    assert setup.instrument_framework("ghost", TracerProvider(), required=False) is False  # silently skipped
    with pytest.raises(RuntimeError, match=r"agenttrace\[ghost\]"):
        setup.instrument_framework("ghost", TracerProvider(), required=True)


def test_requested_framework_is_instrumented_with_our_provider(monkeypatch):
    calls = []

    class FakeInstrumentor:
        def instrument(self, tracer_provider):
            calls.append(tracer_provider)

    fake_module = types.SimpleNamespace(FakeInstrumentor=FakeInstrumentor)
    monkeypatch.setitem(setup.INSTRUMENTORS, "fake", ("fake_module", "FakeInstrumentor"))
    monkeypatch.setattr(setup.importlib, "import_module", lambda name: fake_module)
    provider = TracerProvider()
    assert setup.instrument_framework("fake", provider, required=True) is True
    assert calls == [provider]


def test_init_instruments_requested_frameworks_and_langchain_by_default(monkeypatch):
    seen = []
    monkeypatch.setattr(setup, "instrument_framework", lambda name, provider, required: seen.append((name, required)))
    provider = setup.init("test-agent", instrument=["openai"])
    try:
        assert seen == [("openai", True), ("langchain", False)]  # explicit = required, default LangChain = optional
    finally:
        provider.shutdown()


def test_context_is_a_usable_context_manager():
    with setup.context(session_id="s1", user_id="u1", tags=["demo"]):
        pass  # no error, with or without the optional instrumentation package


def test_context_without_the_optional_package_does_nothing(monkeypatch):
    monkeypatch.setattr(setup, "using_attributes", None)
    with setup.context(session_id="s1"):
        pass
