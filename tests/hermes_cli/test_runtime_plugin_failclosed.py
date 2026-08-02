"""Fail-closed guarantees of the generic runtime-provider seam.

Plugin hook code is untrusted: its exceptions may embed credentials. Every
seam boundary must replace plugin exceptions with fixed-message typed errors
(``from None``), and log sinks must never render plugin-controlled text.
"""

from __future__ import annotations

import traceback

import pytest

import providers
from providers import create_provider_client, register_provider
from providers.base import ProviderProfile
from providers.runtime import (
    ProviderRuntimeHooks,
    RuntimeClientRequest,
    RuntimeResolution,
)
from hermes_cli import runtime_provider as rp
from hermes_cli.auth import AuthError

SECRET = "unit-test-secret-token-7f3a9c"


@pytest.fixture
def isolated_runtime_registry(monkeypatch):
    monkeypatch.setattr(providers, "_REGISTRY", {})
    monkeypatch.setattr(providers, "_ALIASES", {})
    monkeypatch.setattr(providers, "_RUNTIME_REGISTRY", {})
    monkeypatch.setattr(providers, "_discovered", True)
    monkeypatch.setattr(rp, "resolve_provider", lambda *a, **k: "runtime-test")
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})


def _profile() -> ProviderProfile:
    return ProviderProfile(
        name="runtime-test",
        base_url="https://example.invalid/v1",
        auth_type="oauth_external",
    )


def _formatted(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_resolver_plain_exception_is_sanitized(isolated_runtime_registry):
    def explode(_request):
        raise RuntimeError(f"boom {SECRET}")

    register_provider(
        _profile(), runtime=ProviderRuntimeHooks(resolve_credentials=explode)
    )

    with pytest.raises(AuthError) as exc_info:
        rp.resolve_runtime_provider(requested="runtime-test")

    assert exc_info.value.code == "runtime_plugin_resolver_failed"
    assert exc_info.value.__cause__ is None
    rendered = str(exc_info.value) + _formatted(exc_info.value)
    assert SECRET not in rendered


def test_plugin_raised_auth_error_is_also_sanitized(isolated_runtime_registry):
    def explode(_request):
        raise AuthError(f"plugin-controlled {SECRET}", provider="runtime-test")

    register_provider(
        _profile(), runtime=ProviderRuntimeHooks(resolve_credentials=explode)
    )

    with pytest.raises(AuthError) as exc_info:
        rp.resolve_runtime_provider(requested="runtime-test")

    assert exc_info.value.code == "runtime_plugin_resolver_failed"
    assert SECRET not in str(exc_info.value) + _formatted(exc_info.value)


def test_client_factory_exception_chain_is_sanitized(isolated_runtime_registry):
    def explode(_request):
        raise RuntimeError(f"boom {SECRET}")

    register_provider(
        _profile(), runtime=ProviderRuntimeHooks(create_client=explode)
    )

    with pytest.raises(Exception) as exc_info:
        create_provider_client(
            "runtime-test",
            RuntimeClientRequest(
                provider="runtime-test",
                model="m",
                client_kwargs={"api_key": "k"},
                async_mode=False,
                purpose="primary",
            ),
        )

    assert exc_info.value.__cause__ is None
    assert SECRET not in str(exc_info.value) + _formatted(exc_info.value)


def test_primary_lane_factory_failure_is_controlled(isolated_runtime_registry):
    from agent.agent_runtime_helpers import create_openai_client

    def explode(_request):
        raise RuntimeError(f"boom {SECRET}")

    register_provider(
        _profile(), runtime=ProviderRuntimeHooks(create_client=explode)
    )

    class _Agent:
        provider = "runtime-test"
        model = "m"
        api_mode = "chat_completions"

        @staticmethod
        def _build_keepalive_http_client(*_a, **_k):
            return None

        @staticmethod
        def _client_log_context():
            return "test"

    with pytest.raises(RuntimeError) as exc_info:
        create_openai_client(
            _Agent(),
            {"api_key": "k", "base_url": "https://example.invalid/v1"},
            reason="test",
            shared=False,
        )

    assert "unavailable" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert SECRET not in str(exc_info.value) + _formatted(exc_info.value)


def test_aux_lane_failure_returns_none_and_logs_no_secret(
    isolated_runtime_registry, caplog
):
    from agent.auxiliary_client import resolve_provider_client

    def explode(_request):
        raise RuntimeError(f"boom {SECRET}")

    # The aux branch only engages when the plugin owns client construction;
    # credential resolution then fails inside that branch.
    register_provider(
        _profile(),
        runtime=ProviderRuntimeHooks(
            resolve_credentials=explode,
            create_client=lambda _request: object(),
        ),
    )

    with caplog.at_level("WARNING"):
        client, model = resolve_provider_client("runtime-test", model="m")

    assert client is None and model is None
    assert "credential resolver failed" in caplog.text
    assert SECRET not in caplog.text
    assert "Traceback" not in caplog.text
