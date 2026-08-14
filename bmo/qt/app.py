"""Qt Quick application shell used during the Tk-to-QML migration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from bmo.qt.controller import QtFaceController
from bmo.state import BotStates


QML_PATH = Path(__file__).with_name("qml") / "Main.qml"


def run_qt_face_shell(argv: Sequence[str] | None = None) -> int:
    """Run the isolated Qt face shell without starting assistant services."""
    arguments = list(sys.argv if argv is None else argv)
    app = QGuiApplication(arguments)
    app.setApplicationName("Be More Agent Qt Shell")

    controller = QtFaceController()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bmoUi", controller)
    controller.exitRequested.connect(app.quit)
    controller.menuRequested.connect(
        lambda: controller.set_state(BotStates.IDLE, "Menu request received")
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


__all__ = ["QML_PATH", "run_qt_face_shell"]
