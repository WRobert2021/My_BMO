"""Menu-only, offline Pre-K Learning feature for the BMO kiosk."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import random
from typing import Any, Callable

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)
from bmo.features.learning.config import LearningConfig, load_learning_config
from bmo.features.learning.curriculum import CURRICULUM, Catalog, validate_catalog
from bmo.features.learning.engine import LearningEngine
from bmo.features.learning.store import LearningStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEARNING_MENU_ITEM = FeatureMenuItem(
    name="learning",
    label="Learning",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "learning.png",
)
LearningAppFactory = Callable[..., Any]


def _create_learning_app(*args: Any, **kwargs: Any) -> Any:
    """Construct the Tk Learning view only when its menu item is launched."""
    from bmo.ui.learning import LearningApp

    return LearningApp(*args, **kwargs)


class LearningTool:
    """Own Learning services and expose them only through the touch menu."""

    action = "learning"
    aliases: tuple[str, ...] = ()
    menu_only = True
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        config: LearningConfig,
        *,
        catalog: Catalog = CURRICULUM,
        engine: LearningEngine | None = None,
        store: LearningStore | None = None,
        app_factory: LearningAppFactory = _create_learning_app,
        menu_item: FeatureMenuItem = LEARNING_MENU_ITEM,
    ) -> None:
        validate_catalog(catalog)
        self.config = config
        self.catalog = catalog
        self.engine = engine or LearningEngine(
            catalog,
            rng=random.Random(config.debug_seed),
        )
        data_directory = config.data_directory
        if not data_directory.is_absolute():
            data_directory = PROJECT_ROOT / data_directory
        self.store = store or LearningStore(
            data_directory,
            history_limit=config.history_limit,
            mastery_history_limit=config.mastery_history_limit,
            mastery_threshold=config.mastery_threshold,
            mastery_min_evidence=config.mastery_min_evidence,
        )
        self.menu_item = menu_item
        self._app_factory = app_factory
        self._menu_ui: Any | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        """Reject execution because Learning has no tool-routing surface."""
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        """Return no voice route; Learning starts only from its icon."""
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        """Open one Learning view above its originating menu."""
        if self._menu_ui is not None:
            return

        closed = False

        def handle_close() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            context.cancel_announcements()
            self._menu_ui = None
            context.on_close()

        def announce(text: str, on_complete: Callable[[], None] | None = None) -> bool:
            if not self.config.speech_enabled:
                return False
            return context.announce(text, on_complete)

        try:
            view = self._app_factory(
                context.master,
                config=self.config,
                catalog=self.catalog,
                engine=self.engine,
                store=self.store,
                face_provider=context.current_face,
                announce=announce,
                cancel_announcements=context.cancel_announcements,
                announcements_available=(
                    self.config.speech_enabled
                    and context.announcements_available
                ),
                on_close=handle_close,
            )
            if closed:
                view.close()
                return
            self._menu_ui = view
        except Exception:
            handle_close()
            raise

    def close(self) -> None:
        """Close the current view once; store and engine own no resources."""
        view = self._menu_ui
        if view is not None:
            self._menu_ui = None
            view.close()


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register Learning from its private configuration when menu-visible."""
    # The feature loader overlays shared application settings before invoking
    # this hook. Learning deliberately accepts only its private config path at
    # this boundary so similarly named global settings cannot leak into it.
    private_settings = (
        {"config_path": settings["config_path"]}
        if "config_path" in settings
        else {}
    )
    config = load_learning_config(private_settings, project_root=PROJECT_ROOT)
    if not config.show_in_menu:
        return
    registry.register(LearningTool(config))


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute configured Learning metadata without engine or store objects."""
    private_settings = (
        {"config_path": settings["config_path"]}
        if "config_path" in settings
        else {}
    )
    config = load_learning_config(private_settings, project_root=PROJECT_ROOT)
    if config.show_in_menu:
        registry.register(LEARNING_MENU_ITEM)


__all__ = [
    "CURRICULUM",
    "LEARNING_MENU_ITEM",
    "LearningConfig",
    "LearningEngine",
    "LearningStore",
    "LearningTool",
    "register",
    "register_menu_metadata",
]
