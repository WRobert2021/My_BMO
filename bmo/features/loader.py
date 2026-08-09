"""Configuration-driven feature module loading."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any

from bmo.features.contracts import RuntimeCallback
from bmo.features.registry import ToolRegistry


DEFAULT_FEATURE_MODULES = (
    "bmo.features.get_time",
    "bmo.features.set_timer",
    "bmo.features.get_location",
    "bmo.features.get_weather",
    "bmo.features.search_web",
    "bmo.features.capture_image",
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


def _default_entries() -> list[dict[str, Any]]:
    return [
        {"module": module, "enabled": True, "settings": {}}
        for module in DEFAULT_FEATURE_MODULES
    ]


def _report_failure(
    failures: list[FeatureLoadFailure],
    module: str,
    stage: str,
    exc: object,
    reporter: Callable[[str], None],
) -> None:
    failure = FeatureLoadFailure(
        module,
        stage,
        f"{type(exc).__name__}: {exc}",
    )
    failures.append(failure)
    reporter(str(failure))


def _load_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def load_feature_registry(
    config: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
    shared_settings: Mapping[str, Any] | None = None,
    runtime_callback: RuntimeCallback | None = None,
) -> FeatureLoadResult:
    """Import and register enabled feature modules without failing startup."""
    emit = reporter or (lambda message: print(message, flush=True))
    registry = ToolRegistry(runtime_callback=runtime_callback)
    failures: list[FeatureLoadFailure] = []
    loaded_modules: list[str] = []

    raw_entries = config.get("features", _default_entries())
    if not isinstance(raw_entries, Sequence) or isinstance(
        raw_entries, (str, bytes)
    ):
        _report_failure(
            failures,
            "<features>",
            "configure",
            TypeError("features must be a list"),
            emit,
        )
        return FeatureLoadResult(registry, tuple(failures), ())

    common_settings = dict(shared_settings or {})
    for index, raw_entry in enumerate(raw_entries):
        label = f"<features[{index}]>"
        if not isinstance(raw_entry, Mapping):
            _report_failure(
                failures,
                label,
                "configure",
                TypeError("feature entry must be an object"),
                emit,
            )
            continue

        # Disabled entries are intentionally ignored before validating or
        # importing their module names or settings.
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
                AttributeError("module has no callable register(registry, settings)"),
                emit,
            )
            continue

        try:
            with registry.registration():
                register(registry, settings)
        except Exception as exc:
            _report_failure(failures, module_name, "register", exc, emit)
            continue
        loaded_modules.append(module_name)

    return FeatureLoadResult(
        registry,
        tuple(failures),
        tuple(loaded_modules),
    )
