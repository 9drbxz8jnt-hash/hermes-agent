"""Tests for the model-providers plugin discovery system.

Verifies that:
 1. All bundled providers at plugins/model-providers/<name>/ are discovered
 2. User plugins at $HERMES_HOME/plugins/model-providers/<name>/ override bundled
 3. plugin.yaml manifests with kind=model-provider are correctly categorized
"""

from __future__ import annotations

import sys
from pathlib import Path



REPO_ROOT = Path(__file__).resolve().parents[2]


def _clear_provider_caches():
    """Force providers/__init__.py to re-discover on next list_providers()."""
    import providers as _pkg
    _pkg._REGISTRY.clear()
    _pkg._ALIASES.clear()
    _pkg._PROVIDER_LIST_CACHE = None
    _pkg._discovered = False
    # Evict any cached plugin modules so the next import re-executes.
    for mod in list(sys.modules.keys()):
        if (
            mod.startswith("plugins.model_providers")
            or mod.startswith("_hermes_user_provider")
        ):
            del sys.modules[mod]


def test_bundled_plugins_discovered():
    """Every plugins/model-providers/<name>/ should contain a plugin.yaml + __init__.py."""
    plugins_dir = REPO_ROOT / "plugins" / "model-providers"
    assert plugins_dir.is_dir(), f"Missing {plugins_dir}"

    child_dirs = [c for c in plugins_dir.iterdir() if c.is_dir()]
    assert len(child_dirs) >= 28, f"Expected at least 28 provider plugins, found {len(child_dirs)}"

    for child in child_dirs:
        assert (child / "__init__.py").exists(), f"{child.name} missing __init__.py"
        assert (child / "plugin.yaml").exists(), f"{child.name} missing plugin.yaml"


def test_all_profiles_register():
    """After discovery, the registry must contain every bundled provider directory.

    This is an invariant — the number of profiles matches the number of plugin
    directories, not a hardcoded count. Counts shift when providers are
    added/removed; that's expected and shouldn't break CI.
    """
    _clear_provider_caches()
    from providers import list_providers

    plugins_dir = REPO_ROOT / "plugins" / "model-providers"
    plugin_dir_count = sum(1 for c in plugins_dir.iterdir() if c.is_dir())

    profiles = list_providers()
    names = sorted(p.name for p in profiles)
    # Some plugin __init__.py files register multiple profiles, so the registry
    # count is >= the directory count (never less).
    assert len(names) >= plugin_dir_count, (
        f"Expected at least {plugin_dir_count} profiles (one per plugin dir), got {len(names)}: {names}"
    )

    # Spot-check representative providers from different categories
    for required in (
        "openrouter", "anthropic", "custom", "bedrock", "openai-codex",
        "minimax-oauth", "gmi", "xiaomi", "alibaba-coding-plan", "fireworks",
    ):
        assert required in names, f"Missing profile: {required}"


def test_user_plugin_overrides_bundled(tmp_path, monkeypatch):
    """A user plugin with the same name must override the bundled profile."""
    # Point HERMES_HOME at a fresh temp dir
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    # get_hermes_home() may be module-cached depending on codebase; ensure the
    # env var is the source of truth. Most code paths re-read it each call.

    # Drop a user plugin that replaces 'gmi'
    user_gmi = hermes_home / "plugins" / "model-providers" / "gmi"
    user_gmi.mkdir(parents=True)
    (user_gmi / "__init__.py").write_text(
        "from providers import register_provider\n"
        "from providers.base import ProviderProfile\n"
        "\n"
        "custom_gmi = ProviderProfile(\n"
        '    name="gmi",\n'
        '    aliases=("gmi-user-override-test",),\n'
        '    env_vars=("GMI_API_KEY",),\n'
        '    base_url="https://user-override.example.com/v1",\n'
        '    auth_type="api_key",\n'
        ")\n"
        "register_provider(custom_gmi)\n"
    )
    (user_gmi / "plugin.yaml").write_text(
        "name: gmi-user-override\n"
        "kind: model-provider\n"
        "version: 0.0.1\n"
        "description: Test user override\n"
    )

    _clear_provider_caches()
    from providers import get_provider_profile

    gmi = get_provider_profile("gmi")
    assert gmi is not None
    assert gmi.base_url == "https://user-override.example.com/v1", (
        f"User override not applied; got base_url={gmi.base_url!r}"
    )
    assert "gmi-user-override-test" in gmi.aliases

    # Clean up: reset discovery state so other tests see the bundled version
    _clear_provider_caches()


    # No import means the module must NOT be in the plugins list as a loaded one.
    # We check that the general loader didn't crash and didn't raise from the
    # broken __init__.py.


def test_enabled_root_plugin_can_register_model_provider(tmp_path, monkeypatch):
    """An enabled root plugin can contribute a provider during lazy lookup."""
    hermes_home = tmp_path / ".hermes"
    plugin_dir = hermes_home / "plugins" / "synthetic-runtime"
    plugin_dir.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    (plugin_dir / "plugin.yaml").write_text(
        "name: synthetic-runtime\n"
        "kind: backend\n"
        "version: 0.0.1\n"
        "provides_model_providers:\n"
        "  - synthetic-runtime\n"
        "  - synthetic-runtime-alias\n"
        "description: Synthetic runtime-provider discovery test\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "from providers.base import ProviderProfile\n"
        "\n"
        "def register(ctx):\n"
        "    ctx.register_model_provider(ProviderProfile(\n"
        "        name='synthetic-runtime',\n"
        "        aliases=('synthetic-runtime-alias',),\n"
        "        base_url='https://example.invalid/v1',\n"
        "        auth_type='api_key',\n"
        "    ))\n",
        encoding="utf-8",
    )
    unrelated_dir = hermes_home / "plugins" / "unrelated"
    unrelated_dir.mkdir()
    (unrelated_dir / "plugin.yaml").write_text(
        "name: unrelated\n"
        "kind: standalone\n"
        "version: 0.0.1\n",
        encoding="utf-8",
    )
    (unrelated_dir / "__init__.py").write_text(
        "raise RuntimeError('unrelated plugin must not load during provider discovery')\n",
        encoding="utf-8",
    )
    (hermes_home / "config.yaml").write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - synthetic-runtime\n"
        "    - unrelated\n",
        encoding="utf-8",
    )

    from hermes_cli import plugins as plugins_mod
    from hermes_cli.auth import resolve_provider
    from providers import get_provider_profile

    previous_manager = plugins_mod._plugin_manager
    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    _clear_provider_caches()
    try:
        profile = get_provider_profile("synthetic-runtime-alias")
        assert profile is not None
        assert profile.name == "synthetic-runtime"
        assert profile.base_url == "https://example.invalid/v1"
        assert resolve_provider("synthetic-runtime-alias") == "synthetic-runtime"
        manager = plugins_mod.get_plugin_manager()
        assert manager._plugins["synthetic-runtime"].enabled
        assert "unrelated" not in manager._plugins
    finally:
        _clear_provider_caches()
        plugins_mod._plugin_manager = previous_manager


def _fresh_plugin_manager():
    from hermes_cli import plugins as plugins_mod

    previous_manager = plugins_mod._plugin_manager
    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    return plugins_mod, previous_manager


def _write_root_plugin(
    hermes_home: Path,
    dirname: str,
    *,
    manifest_extra: str,
    init_body: str,
    config_name: str | None = None,
) -> Path:
    plugin_dir = hermes_home / "plugins" / dirname
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        f"name: {config_name or dirname}\n"
        "kind: backend\n"
        "version: 0.0.1\n"
        f"{manifest_extra}",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(init_body, encoding="utf-8")
    return plugin_dir


def test_malformed_model_provider_capability_never_imports(tmp_path, monkeypatch):
    """A falsely-typed capability must not smuggle a plugin into the provider path."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    for idx, bad_value in enumerate(
        ("provides_model_providers: bogus\n", "provides_model_providers: [1, 2]\n", "provides_model_providers: []\n")
    ):
        _write_root_plugin(
            hermes_home,
            f"bad-{idx}",
            manifest_extra=bad_value,
            init_body=(
                "from providers.base import ProviderProfile\n"
                "def register(ctx):\n"
                "    ctx.register_model_provider(ProviderProfile(\n"
                f"        name='bad-{idx}', base_url='https://example.invalid/v1',\n"
                "        auth_type='api_key'))\n"
            ),
        )
    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - bad-0\n    - bad-1\n    - bad-2\n",
        encoding="utf-8",
    )

    plugins_mod, previous_manager = _fresh_plugin_manager()
    _clear_provider_caches()
    try:
        from providers import get_provider_profile

        for idx in range(3):
            assert get_provider_profile(f"bad-{idx}") is None
        loaded = [key for key in plugins_mod._plugin_manager._plugins if key.startswith("bad-")]
        assert loaded == []
    finally:
        _clear_provider_caches()
        plugins_mod._plugin_manager = previous_manager


def test_plugin_declaring_other_provider_not_imported_during_lookup(tmp_path, monkeypatch):
    """Resolving provider X must not import a plugin that only declares Y."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    _write_root_plugin(
        hermes_home,
        "other-plugin",
        manifest_extra="provides_model_providers:\n  - other-provider\n",
        init_body=(
            "from providers.base import ProviderProfile\n"
            "def register(ctx):\n"
            "    ctx.register_model_provider(ProviderProfile(\n"
            "        name='other-provider', base_url='https://example.invalid/v1',\n"
            "        auth_type='api_key'))\n"
        ),
    )
    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - other-plugin\n", encoding="utf-8"
    )

    plugins_mod, previous_manager = _fresh_plugin_manager()
    _clear_provider_caches()
    try:
        from providers import get_provider_profile

        # Lookup of an unrelated provider: plugin must NOT be imported.
        assert get_provider_profile("unrelated-provider") is None
        assert "other-plugin" not in plugins_mod._plugin_manager._plugins
        assert not any(
            mod.startswith("hermes_plugins.other_provider") for mod in sys.modules
        )

        # Targeted lookup of the declared provider: plugin loads.
        profile = get_provider_profile("other-provider")
        assert profile is not None
        assert profile.name == "other-provider"
    finally:
        _clear_provider_caches()
        plugins_mod._plugin_manager = previous_manager


def test_register_model_provider_rejects_undeclared_names(tmp_path, monkeypatch):
    """A plugin may only register providers its manifest declares."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    _write_root_plugin(
        hermes_home,
        "over-claiming",
        manifest_extra="provides_model_providers:\n  - declared-only\n",
        init_body=(
            "from providers.base import ProviderProfile\n"
            "def register(ctx):\n"
            "    ctx.register_model_provider(ProviderProfile(\n"
            "        name='declared-only', aliases=('sneaky-alias',),\n"
            "        base_url='https://example.invalid/v1', auth_type='api_key'))\n"
        ),
    )
    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - over-claiming\n", encoding="utf-8"
    )

    plugins_mod, previous_manager = _fresh_plugin_manager()
    _clear_provider_caches()
    try:
        from providers import get_provider_profile

        assert get_provider_profile("declared-only") is None
        assert get_provider_profile("sneaky-alias") is None
        loaded = plugins_mod._plugin_manager._plugins.get("over-claiming")
        assert loaded is not None
        assert loaded.error is not None
    finally:
        _clear_provider_caches()
        plugins_mod._plugin_manager = previous_manager
