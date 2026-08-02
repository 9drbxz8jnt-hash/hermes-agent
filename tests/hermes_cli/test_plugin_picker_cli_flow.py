"""CLI picker integration for native model-provider plugins.

Covers: the shared row helper (model_switch.plugin_provider_rows), the
explicit-only filter keeping plugin rows, the generic plugin flow writing
config, and the dispatch predicate.
"""

from __future__ import annotations

import providers
from providers.base import ProviderProfile
from providers.runtime import ProviderRuntimeHooks
from hermes_cli import auth as auth_mod
from hermes_cli import inventory
from hermes_cli import main as main_mod
from hermes_cli.model_switch import plugin_provider_rows
from hermes_cli.model_setup_flows import _model_flow_plugin_provider


def _profile() -> ProviderProfile:
    return ProviderProfile(
        name="plugin-cli-test",
        display_name="Plugin CLI Test",
        auth_type="oauth_external",
        base_url="https://example.invalid/v1",
        fallback_models=("plugin-model-a", "plugin-model-b"),
    )


def _install(monkeypatch, runtime):
    profile = _profile()
    monkeypatch.setattr(providers, "list_providers", lambda: [profile])
    monkeypatch.setattr(providers, "get_provider_runtime", lambda _name: runtime)
    monkeypatch.setattr(providers, "get_provider_profile", lambda _name: profile)
    return profile


def test_plugin_provider_rows_helper(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: True,
        ),
    )

    rows = plugin_provider_rows(current_provider="")
    row = next((r for r in rows if r["slug"] == "plugin-cli-test"), None)
    assert row is not None
    assert row["models"] == ["plugin-model-a", "plugin-model-b"]
    assert row["source"] == "plugin"

    # Excluded providers are respected.
    assert plugin_provider_rows(excluded_providers={"plugin-cli-test"}) == []
    # Current-provider flag.
    assert plugin_provider_rows(current_provider="plugin-cli-test")[0]["is_current"] is True


def test_plugin_row_hidden_without_passing_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: False,
        ),
    )
    assert plugin_provider_rows() == []


def test_explicit_filter_keeps_plugin_rows():
    rows = [
        {
            "slug": "google-antigravity",
            "name": "Google Antigravity",
            "source": "plugin",
            "models": ["gemini-3.6-flash-high"],
        }
    ]
    ctx = inventory.ConfigContext(
        current_provider="openai-codex",
        current_base_url="",
        current_model="gpt-5.6-sol",
        user_providers={},
        custom_providers=[],
    )
    kept = inventory._filter_explicit_provider_rows(rows, ctx)
    assert [r["slug"] for r in kept] == ["google-antigravity"]


def test_plugin_flow_writes_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: True,
        ),
    )
    monkeypatch.setattr(
        auth_mod, "_prompt_model_selection", lambda ids, **kw: "plugin-model-a"
    )
    monkeypatch.setattr(auth_mod, "deactivate_provider", lambda: None)

    _model_flow_plugin_provider({}, "plugin-cli-test")

    from hermes_cli.config import load_config

    cfg = load_config()
    model = cfg["model"]
    assert model["provider"] == "plugin-cli-test"
    assert model["default"] == "plugin-model-a"
    assert model["base_url"] == "https://example.invalid/v1"
    assert "api_mode" not in model


def test_plugin_flow_aborts_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _install(
        monkeypatch,
        ProviderRuntimeHooks(
            resolve_credentials=lambda _r: None,
            check_credentials=lambda: False,
        ),
    )
    monkeypatch.setattr(
        auth_mod, "_prompt_model_selection", lambda ids, **kw: "plugin-model-a"
    )

    _model_flow_plugin_provider({}, "plugin-cli-test")

    from hermes_cli.config import load_config

    cfg = load_config()
    # load_config() merges DEFAULT_CONFIG, where model can be a bare string;
    # the point is that the plugin flow never wrote its provider/model.
    model = cfg.get("model")
    model_dict = model if isinstance(model, dict) else {}
    assert model_dict.get("provider") != "plugin-cli-test"
    assert model_dict.get("default") != "plugin-model-a"


def test_runtime_plugin_dispatch_predicate(monkeypatch):
    monkeypatch.setattr(
        providers,
        "get_provider_runtime",
        lambda name: ProviderRuntimeHooks() if name == "plugin-cli-test" else None,
    )
    assert main_mod._is_runtime_plugin_provider("plugin-cli-test") is True
    assert main_mod._is_runtime_plugin_provider("openai") is False
