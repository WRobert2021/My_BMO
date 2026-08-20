"""QML adapter for the local photo album."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl

from bmo.qt.views.base import QtHostedView


class QtAlbumView(QtHostedView):
    kind = "album"
    title = "Album"

    def __init__(
        self,
        host: Any,
        *,
        photo_provider: Any,
        delete_photo: Any,
        request_vision: Any,
        photos_per_page: int,
        on_close: Any,
        face_provider: Any = None,
        bmo_button_path: Any = None,
    ) -> None:
        del face_provider, bmo_button_path
        self.photo_provider = photo_provider
        self.delete_photo = delete_photo
        self.request_vision = request_vision
        self.photos_per_page = max(1, int(photos_per_page))
        self.page = 0
        self.selected: Path | None = None
        self.busy = False
        self.error = ""
        super().__init__(host, on_close=on_close)

    def _photos(self) -> tuple[Path, ...]:
        return tuple(Path(path) for path in self.photo_provider())

    def payload(self) -> dict[str, object]:
        photos = self._photos()
        page_count = max(1, (len(photos) + self.photos_per_page - 1) // self.photos_per_page)
        self.page = min(self.page, page_count - 1)
        start = self.page * self.photos_per_page
        visible = photos[start : start + self.photos_per_page]
        if self.selected not in photos:
            self.selected = None
        return {
            "photos": [
                {
                    "path": str(path),
                    "source": QUrl.fromLocalFile(str(path.resolve())),
                    "label": path.name,
                }
                for path in visible
            ],
            "photoCount": len(photos),
            "pageLabel": f"{self.page + 1} / {page_count}" if photos else "",
            "selectedPath": str(self.selected or ""),
            "selectedSource": (
                QUrl.fromLocalFile(str(self.selected.resolve()))
                if self.selected is not None
                else QUrl()
            ),
            "detail": self.selected is not None,
            "busy": self.busy,
            "error": self.error,
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        if action == "album_select":
            candidate = Path(value)
            self.selected = candidate if candidate in self._photos() else None
        elif action == "album_back":
            self.selected = None
        elif action == "album_next":
            self.page += 1
        elif action == "album_previous":
            self.page = max(0, self.page - 1)
        elif action == "album_delete" and self.selected is not None:
            candidate = self.selected
            try:
                self.delete_photo(candidate)
                self.selected = None
            except (OSError, ValueError) as exc:
                self.error = str(exc) or "BMO could not remove that photo."
        elif action == "album_vision" and self.selected is not None and not self.busy:
            self.busy = True
            self.request_vision(self.selected, self._vision_complete)
        else:
            super().handle_action(action, value)
            return
        self.refresh()

    def _vision_complete(self) -> None:
        self.busy = False
        self.refresh()


__all__ = ["QtAlbumView"]
