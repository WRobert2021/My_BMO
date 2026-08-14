"""Neutral configuration-driven extension loading primitives.

Features and interaction modes own different registries and registration
signatures, but share the same configuration, import, isolation, and rollback
algorithm.  This module keeps that algorithm in one place without making the
two extension systems depend on one another.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from types import ModuleType
from typing import Any, TypeVar


FailureT = TypeVar("FailureT")


def default_extension_entries(modules: Sequence[str]) -> list[dict[str, Any]]:
    """Return fresh enabled configuration records for built-in modules."""
    return [
        {"module": module, "enabled": True, "settings": {}}
        for module in modules
    ]


def load_configured_extensions(
    config: Mapping[str, Any],
    *,
    config_key: str,
    entry_name: str,
    defaults: Sequence[str],
    shared_settings: Mapping[str, Any] | None,
    import_module: Callable[[str], ModuleType],
    registration: Callable[[], AbstractContextManager[Any]],
    invoke_register: Callable[[Callable[..., Any], Mapping[str, Any]], None],
    register_signature: str,
    register_names: Sequence[str] = ("register",),
    make_failure: Callable[[str, str, str], FailureT],
    reporter: Callable[[str], None],
) -> tuple[tuple[FailureT, ...], tuple[str, ...]]:
    """Load independently failing extension modules from one config list."""
    failures: list[FailureT] = []
    loaded_modules: list[str] = []

    def fail(module: str, stage: str, exc: object) -> None:
        failure = make_failure(
            module,
            stage,
            f"{type(exc).__name__}: {exc}",
        )
        failures.append(failure)
        try:
            reporter(str(failure))
        except Exception as report_exc:
            print(
                f"{failure}\n[EXTENSION] Failure reporter raised "
                f"{type(report_exc).__name__}: {report_exc}",
                flush=True,
            )

    missing = object()
    raw_entries = config.get(config_key, missing)
    if raw_entries is missing:
        raw_entries = default_extension_entries(defaults)
    if not isinstance(raw_entries, Sequence) or isinstance(
        raw_entries, (str, bytes)
    ):
        fail(
            f"<{config_key}>",
            "configure",
            TypeError(f"{config_key} must be a list"),
        )
        return tuple(failures), ()

    common_settings = dict(shared_settings or {})
    for index, raw_entry in enumerate(raw_entries):
        label = f"<{config_key}[{index}]>"
        if not isinstance(raw_entry, Mapping):
            fail(
                label,
                "configure",
                TypeError(f"{entry_name} entry must be an object"),
            )
            continue

        # A disabled extension must remain removable even if its stale config
        # would otherwise fail validation.
        enabled = raw_entry.get("enabled", True)
        if not isinstance(enabled, bool):
            fail(
                label,
                "configure",
                TypeError("enabled must be true or false"),
            )
            continue
        if not enabled:
            continue

        module_name = raw_entry.get("module")
        if not isinstance(module_name, str) or not module_name.strip():
            fail(
                label,
                "configure",
                ValueError("module must be a non-empty string"),
            )
            continue
        module_name = module_name.strip()

        raw_settings = raw_entry.get("settings", {})
        if not isinstance(raw_settings, Mapping):
            fail(
                module_name,
                "configure",
                TypeError("settings must be an object"),
            )
            continue
        settings = {**common_settings, **raw_settings}

        try:
            module = import_module(module_name)
        except Exception as exc:
            fail(module_name, "import", exc)
            continue

        try:
            register = next(
                (
                    candidate
                    for name in register_names
                    if callable(candidate := getattr(module, name, None))
                ),
                None,
            )
        except Exception as exc:
            fail(module_name, "register", exc)
            continue
        if not callable(register):
            fail(
                module_name,
                "register",
                AttributeError(
                    f"module has no callable {register_signature}"
                ),
            )
            continue

        try:
            with registration():
                invoke_register(register, settings)
        except Exception as exc:
            fail(module_name, "register", exc)
            continue
        loaded_modules.append(module_name)

    return tuple(failures), tuple(loaded_modules)
