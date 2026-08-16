"""UI-neutral runtime ownership for live menu catalogs and launch requests."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from bmo.menu_catalog import (
    MenuCatalog,
    MenuContribution,
    MenuOwner,
    MenuSelectionRequest,
)


CatalogProvider = Callable[[], MenuCatalog]
MenuLauncher = Callable[[str], None]


class MenuContributionRegistry(Protocol):
    """Minimal registry surface needed to build a current menu catalog."""

    @property
    def menu_items(self) -> Iterable[MenuContribution]:
        """Return enabled contributions in registration order."""


class RuntimeMenuCoordinator:
    """Snapshot visible metadata and dispatch validated selections by owner."""

    def __init__(
        self,
        catalog_provider: CatalogProvider,
        *,
        launch_mode: MenuLauncher,
        launch_feature: MenuLauncher,
    ) -> None:
        for name, callback in (
            ("catalog_provider", catalog_provider),
            ("launch_mode", launch_mode),
            ("launch_feature", launch_feature),
        ):
            if not callable(callback):
                raise TypeError(f"Runtime menu {name} must be callable.")
        self._catalog_provider = catalog_provider
        self._launch_mode = launch_mode
        self._launch_feature = launch_feature

    @classmethod
    def from_registries(
        cls,
        mode_registry: MenuContributionRegistry,
        feature_registry: MenuContributionRegistry,
        *,
        launch_mode: MenuLauncher,
        launch_feature: MenuLauncher,
    ) -> RuntimeMenuCoordinator:
        """Build live catalog snapshots from the two extension registries."""
        if not hasattr(mode_registry, "menu_items"):
            raise TypeError("Mode registry must expose menu_items.")
        if not hasattr(feature_registry, "menu_items"):
            raise TypeError("Feature registry must expose menu_items.")

        def catalog_provider() -> MenuCatalog:
            return MenuCatalog.from_contributions(
                modes=mode_registry.menu_items,
                features=feature_registry.menu_items,
            )

        return cls(
            catalog_provider,
            launch_mode=launch_mode,
            launch_feature=launch_feature,
        )

    def catalog(self) -> MenuCatalog:
        """Return one validated snapshot of currently visible contributions."""
        catalog = self._catalog_provider()
        if not isinstance(catalog, MenuCatalog):
            raise TypeError("Runtime menu catalog provider must return MenuCatalog.")
        return catalog

    def dispatch(self, request: MenuSelectionRequest) -> None:
        """Launch one currently visible request through its owning callback."""
        if not isinstance(request, MenuSelectionRequest):
            raise TypeError("Runtime menu dispatch requires MenuSelectionRequest.")
        current = self.catalog().request_for(request.key)
        if current.owner == MenuOwner.MODE:
            self._launch_mode(current.name)
            return
        self._launch_feature(current.name)


__all__ = [
    "CatalogProvider",
    "MenuContributionRegistry",
    "MenuLauncher",
    "RuntimeMenuCoordinator",
]
