"""Qt Quick application shell used during the Tk-to-QML migration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from bmo.face_config import PROJECT_ROOT
from bmo.menu_model import IconMenuItem
from bmo.qt.controller import QtFaceController
from bmo.state import BotStates


QML_PATH = Path(__file__).with_name("qml") / "Main.qml"


def preview_menu_items(
    project_root: Path = PROJECT_ROOT,
) -> tuple[IconMenuItem, ...]:
    """Return a disposable visual menu for the isolated QML shell."""
    icon_root = Path(project_root) / "graphics" / "icons"
    definitions = (
        ("matching_game", "Pup Pairs", "matching_game.png"),
        ("twenty_questions", "20 Questions", "20_questions.png"),
        ("get_weather", "Weather", "weather.png"),
        ("set_timer", "Timer", "timer.png"),
        ("calendar", "Calendar", "calendar.png"),
        ("album", "Album", "album.png"),
        ("learning", "Learning", "learning.png"),
    )
    return tuple(
        IconMenuItem(name, label, icon_root / filename)
        for name, label, filename in definitions
    )


def run_qt_face_shell(argv: Sequence[str] | None = None) -> int:
    """Run the isolated Qt face shell without starting assistant services."""
    arguments = list(sys.argv if argv is None else argv)
    app = QGuiApplication(arguments)
    app.setApplicationName("Be More Agent Qt Shell")

    controller = QtFaceController(menu_items=preview_menu_items())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bmoUi", controller)
    controller.exitRequested.connect(app.quit)
    controller.menuRequested.connect(
        lambda: print("[QT MENU] opened", flush=True)
    )
    controller.menuItemSelected.connect(
        lambda action: print(f"[QT MENU] selected: {action}", flush=True)
    )
    controller.pushToTalkRequested.connect(
        lambda: controller.set_state(BotStates.LISTENING, "PTT request received")
    )
    controller.interruptRequested.connect(
        lambda: controller.set_state(BotStates.IDLE, "Interrupt request received")
    )
    engine.quit.connect(app.quit)
    app.aboutToQuit.connect(controller.stop)
    engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
    if not engine.rootObjects():
        controller.stop()
        print(f"Could not load QML shell: {QML_PATH}", flush=True)
        return 1

    QTimer.singleShot(
        0,
        lambda: controller.set_state(
            BotStates.IDLE,
            "Qt/QML face shell ready",
        ),
    )
    print(
        f"Qt/QML face shell: platform={app.platformName()} qml={QML_PATH}",
        flush=True,
    )
    return app.exec()


__all__ = ["QML_PATH", "preview_menu_items", "run_qt_face_shell"]
