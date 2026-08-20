"""Configuration-driven feature module loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any

from bmo.extensions import load_configured_extensions
from bmo.features.contracts import RuntimeAttentionCallback, RuntimeCallback
from bmo.features.registry import ToolRegistry


DEFAULT_ROUTABLE_FEATURE_MODULES = (
    "bmo.features.get_time",
    "bmo.features.set_timer",
    "bmo.features.calendar",
    "bmo.features.get_location",
    "bmo.features.get_weather",
    "bmo.features.search_web",
    "bmo.features.capture_image",
)
DEFAULT_MENU_FEATURE_MODULES = (
    "bmo.features.album",
    "bmo.features.learning",
    "bmo.features.galaxy_rvr",
)
DEFAULT_FEATURE_MODULES = (
    *DEFAULT_ROUTABLE_FEATURE_MODULES,
    *DEFAULT_MENU_FEATURE_MODULES,
)


@dataclass(frozen=True)
class FeatureLoadFailure:
    """One isolated configuration, import, or registration failure."""

    module: str
    stage: str
    error: str

    def __str__(self) -> str:
        return (
            f"[FEATURE] Could not {self.stage} enabled module "
            f"'{self.module}': {self.error}"
        )


@dataclass(frozen=True)
class FeatureLoadResult:
    """The usable registry plus non-fatal failures encountered while loading."""

    registry: ToolRegistry
    failures: tuple[FeatureLoadFailure, ...]
    modules: tuple[str, ...]


def _load_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def load_feature_registry(
    config: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
    shared_settings: Mapping[str, Any] | None = None,
    runtime_callback: RuntimeCallback | None = None,
    attention_callback: RuntimeAttentionCallback | None = None,
    metadata_only: bool = False,
) -> FeatureLoadResult:
    """Import and register enabled feature modules without failing startup."""
    emit = reporter or (lambda message: print(message, flush=True))
    registry = ToolRegistry(
        runtime_callback=runtime_callback,
        attention_callback=attention_callback,
    )
    failures, loaded_modules = load_configured_extensions(
        config,
        config_key="features",
        entry_name="feature",
        defaults=DEFAULT_FEATURE_MODULES,
        shared_settings=shared_settings,
        import_module=_load_module,
        registration=registry.registration,
        invoke_register=lambda register, settings: register(registry, settings),
        register_signature="register(registry, settings)",
        register_names=(
            ("register_metadata", "register")
            if metadata_only
            else ("register",)
        ),
        make_failure=FeatureLoadFailure,
        reporter=emit,
    )

    return FeatureLoadResult(
        registry,
        failures,
        loaded_modules,
    )
