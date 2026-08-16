"""Menu-only photo album with contained browsing and recoverable deletion."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PHOTO_ROOT = Path.home() / "Pictures"
DEFAULT_WASTEBASKET_ROOT = Path.home() / ".local" / "share" / "Trash"
DEFAULT_BMO_BUTTON = (
    PROJECT_ROOT / "faces" / "capturing" / "capturing 01.png"
)
ALBUM_MENU_ITEM = FeatureMenuItem(
    name="album",
    label="Album",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "album.png",
)
PHOTO_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)
AlbumAppFactory = Callable[..., Any]


def _create_album_app(*args: Any, **kwargs: Any) -> Any:
    """Construct the Tk album view only when its menu item is launched."""
    from bmo.ui.album import AlbumApp

    return AlbumApp(*args, **kwargs)


class AlbumLibrary:
    """Own the configured photo boundary and Wastebasket operations."""

    def __init__(
        self,
        photo_root: str | Path,
        wastebasket_root: str | Path,
    ) -> None:
        self.photo_root = Path(photo_root).expanduser().resolve()
        self.wastebasket_root = Path(wastebasket_root).expanduser().resolve()

    def photo_paths(self) -> tuple[Path, ...]:
        """Return contained regular image files, newest first."""
        photos: dict[Path, int] = {}
        try:
            candidates = self.photo_root.rglob("*")
            for candidate in candidates:
                if (
                    candidate.is_symlink()
                    or candidate.suffix.casefold() not in PHOTO_EXTENSIONS
                ):
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if not resolved.is_file():
                        continue
                    self._require_contained(resolved)
                    if self._is_within(resolved, self.wastebasket_root):
                        continue
                    photos[resolved] = resolved.stat().st_mtime_ns
                except (OSError, PermissionError, RuntimeError, ValueError):
                    continue
        except OSError:
            return ()
        return tuple(
            path
            for path, _ in sorted(
                photos.items(),
                key=lambda item: (-item[1], str(item[0]).casefold()),
            )
        )

    def require_photo(self, photo_path: str | Path) -> Path:
        """Resolve one current regular photo inside the configured root."""
        supplied = Path(photo_path)
        if supplied.is_symlink():
            raise PermissionError("Album does not operate on symbolic links.")
        resolved = supplied.resolve(strict=True)
        self._require_contained(resolved)
        if not resolved.is_file():
            raise ValueError("Album selection is not a regular file.")
        if resolved.suffix.casefold() not in PHOTO_EXTENSIONS:
            raise ValueError("Album selection is not a supported image.")
        if self._is_within(resolved, self.wastebasket_root):
            raise PermissionError("Wastebasket files are outside the album.")
        return resolved

    def move_to_wastebasket(self, photo_path: str | Path) -> Path:
        """Move a contained photo into the user's FreeDesktop Wastebasket."""
        source = self.require_photo(photo_path)
        files_directory = self.wastebasket_root / "files"
        info_directory = self.wastebasket_root / "info"
        files_directory.mkdir(parents=True, exist_ok=True)
        info_directory.mkdir(parents=True, exist_ok=True)
        destination = self._available_destination(files_directory, source.name)
        info_path = info_directory / f"{destination.name}.trashinfo"
        temporary_info = info_directory / (
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary_info.write_text(
            "[Trash Info]\n"
            f"Path={quote(str(source), safe='/')}\n"
            f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n",
            encoding="utf-8",
        )

        moved = False
        try:
            shutil.move(str(source), str(destination))
            moved = True
            temporary_info.replace(info_path)
        except Exception:
            if moved and destination.exists() and not source.exists():
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                except OSError:
                    pass
            raise
        finally:
            temporary_info.unlink(missing_ok=True)
        return destination

    def _require_contained(self, path: Path) -> None:
        if not self._is_within(path, self.photo_root):
            raise PermissionError(
                "Album paths must stay inside the configured photo root."
            )

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _available_destination(directory: Path, filename: str) -> Path:
        destination = directory / filename
        if not destination.exists():
            return destination
        supplied = Path(filename)
        counter = 1
        while True:
            destination = directory / (
                f"{supplied.stem}.{counter}{supplied.suffix}"
            )
            if not destination.exists():
                return destination
            counter += 1


class AlbumTool:
    """Register a menu view without exposing a voice/model action."""

    action = "album"
    aliases: tuple[str, ...] = ()
    menu_only = True
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        library: AlbumLibrary,
        *,
        bmo_button_path: str | Path = DEFAULT_BMO_BUTTON,
        photos_per_page: int = 6,
        app_factory: AlbumAppFactory = _create_album_app,
        menu_item: FeatureMenuItem = ALBUM_MENU_ITEM,
    ) -> None:
        self.library = library
        self.bmo_button_path = Path(bmo_button_path).expanduser()
        self.photos_per_page = photos_per_page
        self._app_factory = app_factory
        self.menu_item = menu_item
        self._menu_ui: Any | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        """Open the album only through its registered menu contribution."""
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            self._menu_ui = None
            context.on_close()

        def request_vision(
            photo_path: Path,
            on_complete: Callable[[], None],
        ) -> None:
            contained_path = self.library.require_photo(photo_path)
            context.request_vision(contained_path, on_complete)

        try:
            self._menu_ui = self._app_factory(
                context.master,
                photo_provider=self.library.photo_paths,
                delete_photo=self.library.move_to_wastebasket,
                face_provider=context.current_face,
                request_vision=request_vision,
                bmo_button_path=self.bmo_button_path,
                photos_per_page=self.photos_per_page,
                on_close=handle_close,
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    def close(self) -> None:
        menu_ui = self._menu_ui
        if menu_ui is not None:
            menu_ui.close()


def _path_setting(
    settings: Mapping[str, Any],
    key: str,
    default: Path,
) -> Path:
    value = settings.get(key, default)
    if not isinstance(value, (str, Path)):
        raise TypeError(f"album {key} must be a path string")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"album {key} must not be empty")
    return Path(value).expanduser()


def _photos_per_page_setting(settings: Mapping[str, Any]) -> int:
    value = settings.get("photos_per_page", 6)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("album photos_per_page must be an integer")
    if value < 2 or value > 6:
        raise ValueError("album photos_per_page must be between 2 and 6")
    return value


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register the contained, menu-only album from module settings."""
    library = AlbumLibrary(
        _path_setting(settings, "photo_root", DEFAULT_PHOTO_ROOT),
        _path_setting(
            settings,
            "wastebasket_root",
            DEFAULT_WASTEBASKET_ROOT,
        ),
    )
    registry.register(
        AlbumTool(
            library,
            bmo_button_path=_path_setting(
                settings,
                "bmo_button_image",
                DEFAULT_BMO_BUTTON,
            ),
            photos_per_page=_photos_per_page_setting(settings),
        )
    )


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Validate Album settings and contribute metadata without a library."""
    _path_setting(settings, "photo_root", DEFAULT_PHOTO_ROOT)
    _path_setting(settings, "wastebasket_root", DEFAULT_WASTEBASKET_ROOT)
    _path_setting(settings, "bmo_button_image", DEFAULT_BMO_BUTTON)
    _photos_per_page_setting(settings)
    registry.register(ALBUM_MENU_ITEM)
