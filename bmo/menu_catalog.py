"""Typed, UI-toolkit-neutral menu catalog and selection requests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from bmo.menu_model import IconMenuItem


class MenuContribution(Protocol):
    """Structural metadata supplied by a feature or mode registry."""

    name: str
    label: str
    icon_path: Path


class MenuOwner(str, Enum):
    """Registry that owns a selected menu contribution."""

    MODE = "mode"
    FEATURE = "feature"


@dataclass(frozen=True)
class MenuSelectionRequest:
    """One validated request to launch a registry-owned menu contribution."""

    owner: MenuOwner
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.owner, MenuOwner):
            raise TypeError("Menu selection owner must be a MenuOwner.")
        normalized = str(self.name).strip().lower()
        if not normalized or ":" in normalized:
            raise ValueError("Menu selection name must be non-empty and unqualified.")
        object.__setattr__(self, "name", normalized)

    @property
    def key(self) -> str:
        return f"{self.owner.value}:{self.name}"

    @classmethod
    def parse(cls, value: str) -> MenuSelectionRequest:
        """Parse the stable namespaced key exposed by menu views."""
        owner, separator, name = str(value).strip().lower().partition(":")
        if not separator or not name:
            raise LookupError(f"Invalid menu selection '{value}'.")
        try:
            parsed_owner = MenuOwner(owner)
        except ValueError as exc:
            raise LookupError(f"Unknown menu selection kind '{owner}'.") from exc
        try:
            return cls(parsed_owner, name)
        except (TypeError, ValueError) as exc:
            raise LookupError(f"Invalid menu selection '{value}'.") from exc


@dataclass(frozen=True)
class MenuCatalog:
    """Ordered presentation items backed by typed launch requests."""

    items: tuple[IconMenuItem, ...] = ()

    def __post_init__(self) -> None:
        supplied = tuple(self.items)
        if not all(isinstance(item, IconMenuItem) for item in supplied):
            raise TypeError("Menu catalog items must be IconMenuItem instances.")
        names = tuple(item.name for item in supplied)
        if len(set(names)) != len(names):
            raise ValueError("Menu catalog item names must be unique.")
        for name in names:
            MenuSelectionRequest.parse(name)
        object.__setattr__(self, "items", supplied)

    def request_for(self, key: str) -> MenuSelectionRequest:
        """Resolve a visible item key into its typed launch request."""
        request = MenuSelectionRequest.parse(key)
        if request.key not in {item.name for item in self.items}:
            raise LookupError(f"No visible menu item named '{request.key}'.")
        return request

    @classmethod
    def from_contributions(
        cls,
        *,
        modes: Iterable[MenuContribution] = (),
        features: Iterable[MenuContribution] = (),
    ) -> MenuCatalog:
        """Compose registry order with modes before features, matching Tk."""
        items = tuple(
            IconMenuItem(
                MenuSelectionRequest(MenuOwner.MODE, item.name).key,
                item.label,
                item.icon_path,
            )
            for item in modes
        ) + tuple(
            IconMenuItem(
                MenuSelectionRequest(MenuOwner.FEATURE, item.name).key,
                item.label,
                item.icon_path,
            )
            for item in features
        )
        return cls(items)


__all__ = [
    "MenuCatalog",
    "MenuContribution",
    "MenuOwner",
    "MenuSelectionRequest",
]
