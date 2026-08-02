"""Versioned executable hooks for native model-provider plugins.

``ProviderProfile`` remains declarative. Plugins that own credentials or need a
native client facade register this small hook bundle beside their profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping


RUNTIME_PROVIDER_API_VERSION = 1
RuntimePurpose = Literal["primary", "auxiliary", "fallback"]


class ProviderRuntimeError(RuntimeError):
    """A registered provider runtime could not safely serve a request."""


def _copy_value(value: Any) -> Any:
    """Copy built-in containers without touching opaque SDK objects."""
    if isinstance(value, Mapping):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_value(item) for item in value)
    if isinstance(value, set):
        return {_copy_value(item) for item in value}
    return value


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(_copy_value(value or {}))


@dataclass(frozen=True)
class RuntimeCredentialRequest:
    """Safe inputs supplied to a plugin credential resolver."""

    provider: str
    requested_provider: str
    explicit_api_key: str = ""
    explicit_base_url: str = ""
    target_model: str | None = None
    model_config: Mapping[str, Any] = field(default_factory=dict)
    purpose: RuntimePurpose = "primary"

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_config", _frozen_mapping(self.model_config))


@dataclass(frozen=True)
class RuntimeResolution:
    """The credential resolver's validated, transport-neutral result."""

    provider: str
    api_key: str
    base_url: str
    api_mode: str = "chat_completions"
    source: str = "runtime-plugin"


@dataclass(frozen=True)
class RuntimeClientRequest:
    """Inputs supplied to a plugin native-client factory."""

    provider: str
    model: str | None
    client_kwargs: Mapping[str, Any]
    async_mode: bool
    purpose: RuntimePurpose
    reason: str = ""
    shared: bool = False
    api_mode: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_kwargs", _frozen_mapping(self.client_kwargs))


@dataclass(frozen=True)
class ProviderRuntimeHooks:
    """Optional executable behavior owned by one model-provider plugin."""

    api_version: int = RUNTIME_PROVIDER_API_VERSION
    resolve_credentials: Callable[[RuntimeCredentialRequest], RuntimeResolution] | None = None
    create_client: Callable[[RuntimeClientRequest], Any] | None = None
    # Cheap, offline credential-presence probe for picker/inventory surfaces.
    # Must never perform network I/O, OAuth refreshes, or credential writes.
    check_credentials: Callable[[], bool] | None = None


def validate_runtime_hooks(runtime: ProviderRuntimeHooks) -> None:
    """Reject an incompatible hook bundle before mutating provider state."""
    if not isinstance(runtime, ProviderRuntimeHooks):
        raise TypeError("runtime must be a providers.runtime.ProviderRuntimeHooks")
    if runtime.api_version != RUNTIME_PROVIDER_API_VERSION:
        raise ValueError(
            "unsupported runtime provider API version "
            f"{runtime.api_version}; expected {RUNTIME_PROVIDER_API_VERSION}"
        )
    if runtime.resolve_credentials is None and runtime.create_client is None:
        raise ValueError("runtime provider hooks must expose at least one capability")
    for name in ("resolve_credentials", "create_client", "check_credentials"):
        hook = getattr(runtime, name)
        if hook is not None and not callable(hook):
            raise TypeError(f"runtime provider hook {name} must be callable")
