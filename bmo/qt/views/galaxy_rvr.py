"""QML adapter for the GalaxyRVR controller remote."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl

from bmo.features.galaxy_rvr import GalaxyRVRStatus
from bmo.features.galaxy_rvr_config import GalaxyRVRConfig
from bmo.qt.views.base import QtHostedView


class QtGalaxyRVRView(QtHostedView):
    kind = "galaxy_rvr"
    title = "GalaxyRVR Remote"

    def __init__(
        self,
        host: Any,
        *,
        config: GalaxyRVRConfig,
        session_factory: Any,
        on_close: Any,
        face_provider: Any = None,
    ) -> None:
        del face_provider
        self.config = config
        self.status = GalaxyRVRStatus(
            servo_angle=config.servo_start_angle,
        )
        self.session = session_factory(self._status_changed)
        super().__init__(host, on_close=on_close)
        self.session.start()

    def payload(self) -> dict[str, object]:
        status = self.status.to_json()
        photo = Path(self.status.last_photo) if self.status.last_photo else None
        return {
            **status,
            "host": self.config.host,
            "captureUrl": self.config.capture_url,
            "previewEnabled": self.config.preview_enabled,
            "previewIntervalMs": round(1000 / self.config.preview_fps),
            "lastPhotoSource": (
                QUrl.fromLocalFile(str(photo.resolve())) if photo else QUrl()
            ),
            "controls": [
                "Left stick  •  drive",
                "Right stick  •  steer",
                "LT / RT  •  camera tilt",
                "A button  •  snap photo",
            ],
            "lightColors": [
                {"name": "OFF", "hex": "#000000", "text": "#ffffff"},
                {"name": "RED", "hex": "#ef5350", "text": "#ffffff"},
                {"name": "GOLD", "hex": "#f2c84b", "text": "#102a5e"},
                {"name": "GREEN", "hex": "#43b581", "text": "#ffffff"},
                {"name": "BLUE", "hex": "#3f8efc", "text": "#ffffff"},
                {"name": "PURPLE", "hex": "#9b6de3", "text": "#ffffff"},
                {"name": "PINK", "hex": "#f08aa6", "text": "#102a5e"},
                {"name": "WHITE", "hex": "#ffffff", "text": "#102a5e"},
            ],
        }

    def _status_changed(self, status: GalaxyRVRStatus) -> None:
        self.status = status
        self.refresh()

    def handle_action(self, action: str, value: str) -> None:
        if action == "galaxy_rvr_snapshot":
            self.session.request_snapshot()
        elif action == "galaxy_rvr_rgb":
            color = value.strip().removeprefix("#")
            if len(color) != 6:
                return
            try:
                red, green, blue = (
                    int(color[index : index + 2], 16)
                    for index in (0, 2, 4)
                )
            except ValueError:
                return
            self.session.request_rgb(red, green, blue)
        else:
            super().handle_action(action, value)
            return
        self.refresh()

    def close(self) -> None:
        if self.closed:
            return
        self.session.close()
        super().close()


__all__ = ["QtGalaxyRVRView"]
