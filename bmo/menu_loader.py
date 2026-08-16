"""Resource-free configured menu metadata loading for presentation shells."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Any, Generic, TypeVar

from bmo.extensions import load_configured_extensions
from bmo.features.contracts import FeatureMenuItem
from bmo.features.loader import DEFAULT_FEATURE_MODULES
from bmo.menu_catalog import MenuCatalog, MenuOwner, MenuSelectionRequest
from bmo.modes.contracts import ModeMenuItem
from bmo.modes.loader import DEFAULT_MODE_MODULES


MenuItemT = TypeVar("MenuItemT", FeatureMenuItem, ModeMenuItem)


class _MenuMetadataRegistry(Generic[MenuItemT]):
    """Collect one owner type with transactional duplicate validation."""

    def __init__(
        self,
        item_type: type[MenuItemT],
        owner: MenuOwner,
    ) -> None:
        self._item_type = item_type
        self._owner = owner
        self._items: list[MenuItemT] = []

    @property
    def items(self) -> tuple[MenuItemT, ...]:
        return tuple(self._items)

    def register(self, item: MenuItemT) -> None:
        if not isinstance(item, self._item_type):
            raise TypeError(
                f"Menu metadata must be {self._item_type.__name__}."
            )
        MenuSelectionRequest(self._owner, item.name)
        if any(existing.name == item.name for existing in self._items):
            raise ValueError(f"Duplicate menu metadata name '{item.name}'.")
        self._items.append(item)

    @contextmanager
    def registration(self) -> Iterator[None]:
        size_before = len(self._items)
        try:
            yield
        except BaseException:
            del self._items[size_before:]
            raise


@dataclass(frozen=True)
class MenuCatalogLoadFailure:
    """One isolated menu configuration, import, or metadata failure."""

    owner: MenuOwner
    module: str
    stage: str
    error: str

    def __str__(self) -> str:
        return (
            f"[MENU {self.owner.value.upper()}] Could not {self.stage} "
            f"enabled module '{self.module}': {self.error}"
        )


@dataclass(frozen=True)
class MenuCatalogLoadResult:
    """Configured menu catalog plus isolated metadata-load diagnostics."""

    catalog: MenuCatalog
    failures: tuple[MenuCatalogLoadFailure, ...]
    feature_modules: tuple[str, ...]
    mode_modules: tuple[str, ...]


def _load_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def _failure_factory(
    owner: MenuOwner,
) -> Callable[[str, str, str], MenuCatalogLoadFailure]:
    return lambda module, stage, error: MenuCatalogLoadFailure(
        owner,
        module,
        stage,
        error,
    )


def load_menu_catalog(
    config: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
    shared_settings: Mapping[str, Any] | None = None,
) -> MenuCatalogLoadResult:
    """Load enabled extension menu metadata without constructing runtimes."""
    if not isinstance(config, Mapping):
        raise TypeError("Menu catalog configuration must be a mapping.")
    emit = reporter or (lambda message: print(message, flush=True))
    common_settings = dict(
        shared_settings
        if shared_settings is not None
        else {
            key: value
            for key, value in config.items()
            if key not in {"features", "modes"}
        }
    )
    feature_registry = _MenuMetadataRegistry(
        FeatureMenuItem,
        MenuOwner.FEATURE,
    )
    feature_failures, feature_modules = load_configured_extensions(
        config,
        config_key="features",
        entry_name="feature",
        defaults=DEFAULT_FEATURE_MODULES,
        shared_settings=common_settings,
        import_module=_load_module,
        registration=feature_registry.registration,
        invoke_register=lambda register, settings: register(
            feature_registry,
            settings,
        ),
        register_signature="register_menu_metadata(registry, settings)",
        register_names=("register_menu_metadata",),
        allow_missing_register=True,
        make_failure=_failure_factory(MenuOwner.FEATURE),
        reporter=emit,
    )
    mode_registry = _MenuMetadataRegistry(
        ModeMenuItem,
        MenuOwner.MODE,
    )
    mode_failures, mode_modules = load_configured_extensions(
        config,
        config_key="modes",
        entry_name="mode",
        defaults=DEFAULT_MODE_MODULES,
        shared_settings=common_settings,
        import_module=_load_module,
        registration=mode_registry.registration,
        invoke_register=lambda register, settings: register(
            mode_registry,
            settings,
        ),
        register_signature="register_menu_metadata(registry, settings)",
        register_names=("register_menu_metadata",),
        allow_missing_register=True,
        make_failure=_failure_factory(MenuOwner.MODE),
        reporter=emit,
    )
    return MenuCatalogLoadResult(
        MenuCatalog.from_contributions(
            modes=mode_registry.items,
            features=feature_registry.items,
        ),
        (*feature_failures, *mode_failures),
        feature_modules,
        mode_modules,
    )


__all__ = [
    "MenuCatalogLoadFailure",
    "MenuCatalogLoadResult",
    "load_menu_catalog",
]
