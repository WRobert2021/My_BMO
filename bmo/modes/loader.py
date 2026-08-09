"""Configuration-driven interaction mode loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any

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


def _default_entries() -> list[dict[str, Any]]:
    return [
        {"module": module, "enabled": True, "settings": {}}
        for module in DEFAULT_MODE_MODULES
    ]


def _report_failure(
    failures: list[ModeLoadFailure],
    module: str,
    stage: str,
    exc: object,
    reporter: Callable[[str], None],
) -> None:
    failure = ModeLoadFailure(
        module,
        stage,
        f"{type(exc).__name__}: {exc}",
    )
    failures.append(failure)
    reporter(str(failure))


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
    failures: list[ModeLoadFailure] = []
    loaded_modules: list[str] = []

    raw_entries = config.get("modes", _default_entries())
    if not isinstance(raw_entries, Sequence) or isinstance(
        raw_entries, (str, bytes)
    ):
        _report_failure(
            failures,
            "<modes>",
            "configure",
            TypeError("modes must be a list"),
            emit,
        )
        return ModeLoadResult(registry, tuple(failures), ())

    common_settings = dict(shared_settings or {})
    for index, raw_entry in enumerate(raw_entries):
        label = f"<modes[{index}]>"
        if not isinstance(raw_entry, Mapping):
            _report_failure(
                failures,
                label,
                "configure",
                TypeError("mode entry must be an object"),
                emit,
            )
            continue

        enabled = raw_entry.get("enabled", True)
        if not isinstance(enabled, bool):
            _report_failure(
                failures,
                label,
                "configure",
                TypeError("enabled must be true or false"),
                emit,
            )
            continue
        if not enabled:
            continue

        module_name = raw_entry.get("module")
        if not isinstance(module_name, str) or not module_name.strip():
            _report_failure(
                failures,
                label,
                "configure",
                ValueError("module must be a non-empty string"),
                emit,
            )
            continue
        module_name = module_name.strip()

        raw_settings = raw_entry.get("settings", {})
        if not isinstance(raw_settings, Mapping):
            _report_failure(
                failures,
                module_name,
                "configure",
                TypeError("settings must be an object"),
                emit,
            )
            continue
        settings = {**common_settings, **raw_settings}

        try:
            module = _load_module(module_name)
        except Exception as exc:
            _report_failure(failures, module_name, "import", exc, emit)
            continue

        register = getattr(module, "register", None)
        if not callable(register):
            _report_failure(
                failures,
                module_name,
                "register",
                AttributeError(
                    "module has no callable register(registry, context, settings)"
                ),
                emit,
            )
            continue

        try:
            with registry.registration():
                register(registry, context, settings)
        except Exception as exc:
            _report_failure(failures, module_name, "register", exc, emit)
            continue
        loaded_modules.append(module_name)

    return ModeLoadResult(
        registry,
        tuple(failures),
        tuple(loaded_modules),
    )
