"""Picker rows for native model-provider plugins (model_switch section 2c).

An enabled plugin with a passing OFFLINE credential probe contributes a row
with its declarative fallback_models; anything else stays hidden.
"""

from __future__ import annotations

import providers
from providers.base import ProviderProfile
from providers.runtime import ProviderRuntimeHooks
from hermes_cli.model_switch import list_authenticated_providers


def _profile() -> ProviderProfile:
    return ProviderProfile(
        name="plugin-test",
        display_name="Plugin Test",
        auth_type="oauth_external",
        fallback_models=("plugin-model-a", "plugin-model-b"),
    )


def _install(monkeypatch, runtime):
    profile = _profile()
    monkeypatch.setattr(providers, "list_providers", lambda: [profile])
    monkeypatch.setattr(providers, "get_provider_runtime", lambda _name: runtime)


def _slugs(rows):
    return [row["slug"] for row in rows]


def test_plugin_row_appears_when_offline_probe_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: True,
        ),
    )

    rows = list_authenticated_providers(probe_custom_providers=False)
    row = next((r for r in rows if r["slug"] == "plugin-test"), None)

    assert row is not None
    assert row["models"] == ["plugin-model-a", "plugin-model-b"]
    assert row["total_models"] == 2
    assert row["source"] == "plugin"
    assert row["auth_type"] == "oauth_external"
    assert row["name"] == "Plugin Test"


def test_plugin_row_hidden_when_probe_fails_or_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: False,
        ),
    )
    assert "plugin-test" not in _slugs(
        list_authenticated_providers(probe_custom_providers=False)
    )

    _install(
        monkeypatch,
        ProviderRuntimeHooks(resolve_credentials=lambda _r: None),
    )
    assert "plugin-test" not in _slugs(
        list_authenticated_providers(probe_custom_providers=False)
    )

    _install(monkeypatch, None)
    assert "plugin-test" not in _slugs(
        list_authenticated_providers(probe_custom_providers=False)
    )


def test_plugin_row_hidden_when_probe_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    def explode():
        raise RuntimeError("probe must stay offline and safe")

    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=explode,
        ),
    )
    assert "plugin-test" not in _slugs(
        list_authenticated_providers(probe_custom_providers=False)
    )
