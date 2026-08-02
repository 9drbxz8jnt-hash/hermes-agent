from __future__ import annotations

import pytest

import providers
from providers import (
    create_provider_client,
    get_provider_profile,
    get_provider_runtime,
    register_provider,
)
from providers.base import ProviderProfile
from providers.runtime import (
    ProviderRuntimeError,
    ProviderRuntimeHooks,
    RuntimeClientRequest,
    RuntimeCredentialRequest,
    RuntimeResolution,
)


@pytest.fixture
def isolated_runtime_registry(monkeypatch):
    monkeypatch.setattr(providers, "_REGISTRY", {})
    monkeypatch.setattr(providers, "_ALIASES", {})
    monkeypatch.setattr(providers, "_RUNTIME_REGISTRY", {})
    monkeypatch.setattr(providers, "_discovered", True)


def _profile(*, aliases: tuple[str, ...] = ("runtime-alias",)) -> ProviderProfile:
    return ProviderProfile(
        name="runtime-test",
        aliases=aliases,
        base_url="https://example.invalid/v1",
        auth_type="oauth_external",
    )


def _runtime() -> ProviderRuntimeHooks:
    def resolve(request: RuntimeCredentialRequest) -> RuntimeResolution:
        return RuntimeResolution(
            provider=request.provider,
            api_key="runtime-token",
            base_url="https://example.invalid/v1",
        )

    return ProviderRuntimeHooks(resolve_credentials=resolve)


def test_register_provider_installs_runtime_by_alias(isolated_runtime_registry):
    runtime = _runtime()
    register_provider(_profile(), runtime=runtime)

    assert get_provider_profile("runtime-alias").name == "runtime-test"
    assert get_provider_runtime("runtime-alias") is runtime


def test_replacement_without_runtime_clears_hooks_and_stale_aliases(
    isolated_runtime_registry,
):
    register_provider(_profile(), runtime=_runtime())
    replacement = _profile(aliases=("replacement-alias",))

    register_provider(replacement)

    assert get_provider_runtime("runtime-test") is None
    assert get_provider_profile("runtime-alias") is None
    assert get_provider_profile("replacement-alias") is replacement


def test_invalid_runtime_does_not_partially_register_profile(isolated_runtime_registry):
    incompatible = ProviderRuntimeHooks(api_version=999, resolve_credentials=lambda _r: None)

    with pytest.raises(ValueError, match="unsupported runtime provider API version"):
        register_provider(_profile(), runtime=incompatible)

    assert get_provider_profile("runtime-test") is None
    assert get_provider_runtime("runtime-test") is None


def test_client_factory_failure_is_wrapped_without_plugin_error_text(
    isolated_runtime_registry,
):
    def explode(_request: RuntimeClientRequest):
        raise RuntimeError("synthetic-secret-must-not-escape")

    register_provider(_profile(), runtime=ProviderRuntimeHooks(create_client=explode))

    with pytest.raises(ProviderRuntimeError, match="client factory failed") as exc_info:
        create_provider_client(
            "runtime-test",
            RuntimeClientRequest(
                provider="runtime-test",
                model="test-model",
                client_kwargs={"api_key": "runtime-token"},
                async_mode=False,
                purpose="primary",
            ),
        )

    assert "synthetic-secret-must-not-escape" not in str(exc_info.value)
