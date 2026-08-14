"""Configuration-driven interaction mode loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any

from bmo.extensions import load_configured_extensions
from bmo.modes.contracts import ModeRuntimeContext
from bmo.modes.registry import ModeRegistry


DEFAULT_MODE_MODULES = (
    "bmo.modes.matching_game",
    "bmo.modes.twenty_questions",
)


@dataclass(frozen=True)
class ModeLoadFailure:
    """One isolated configuration, import, or registration failure."""

    module: str
    stage: str
    error: str

    def __str__(self) -> str:
        return (
            f"[MODE] Could not {self.stage} enabled module "
            f"'{self.module}': {self.error}"
        )


@dataclass(frozen=True)
class ModeLoadResult:
    """The usable registry plus non-fatal failures encountered while loading."""

    registry: ModeRegistry
    failures: tuple[ModeLoadFailure, ...]
    modules: tuple[str, ...]


def _load_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def load_mode_registry(
    config: Mapping[str, Any],
    *,
    context: ModeRuntimeContext,
    reporter: Callable[[str], None] | None = None,
    shared_settings: Mapping[str, Any] | None = None,
) -> ModeLoadResult:
    """Import and register enabled mode modules without failing startup."""
    if not isinstance(context, ModeRuntimeContext):
        raise TypeError("Mode loading context must be a ModeRuntimeContext.")

    emit = reporter or (lambda message: print(message, flush=True))
    registry = ModeRegistry()
    failures, loaded_modules = load_configured_extensions(
        config,
        config_key="modes",
        entry_name="mode",
        defaults=DEFAULT_MODE_MODULES,
        shared_settings=shared_settings,
        import_module=_load_module,
        registration=registry.registration,
        invoke_register=lambda register, settings: register(
            registry,
            context,
            settings,
        ),
        register_signature="register(registry, context, settings)",
        make_failure=ModeLoadFailure,
        reporter=emit,
    )

    return ModeLoadResult(
        registry,
        failures,
        loaded_modules,
    )
