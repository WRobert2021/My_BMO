"""Qt Quick launchers for the production assistant and isolated preview."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from bmo.config import load_config
from bmo.face_config import PROJECT_ROOT
from bmo.menu_catalog import MenuCatalog
from bmo.menu_loader import MenuCatalogLoadResult, load_menu_catalog
from bmo.menu_model import IconMenuItem
from bmo.qt.controller import QtFaceController
from bmo.qt.presentation import QtRuntimePresentation
from bmo.qt.view_host import QtViewHost
from bmo.runtime_menu import RuntimeMenuCoordinator
from bmo.state import BotStates


QML_PATH = Path(__file__).with_name("qml") / "Main.qml"


def preview_menu_catalog(
    project_root: Path = PROJECT_ROOT,
) -> MenuCatalog:
    """Return a disposable visual menu for the isolated QML shell."""
    icon_root = Path(project_root) / "graphics" / "icons"
    definitions = (
        ("mode:matching_game", "Pup Pairs", "matching_game.png"),
        ("mode:twenty_questions", "20 Questions", "20_questions.png"),
        ("feature:get_weather", "Weather", "weather.png"),
        ("feature:set_timer", "Timer", "timer.png"),
        ("feature:calendar", "Calendar", "calendar.png"),
        ("feature:album", "Album", "album.png"),
        ("feature:learning", "Learning", "learning.png"),
    )
    return MenuCatalog(
        tuple(
            IconMenuItem(name, label, icon_root / filename)
            for name, label, filename in definitions
        )
    )


def configured_menu_catalog() -> MenuCatalogLoadResult:
    """Load the real configured menu without constructing extension runtimes."""
    return load_menu_catalog(load_config())


def run_qt_face_shell(argv: Sequence[str] | None = None) -> int:
    """Run Qt with configured metadata but without assistant services."""
    arguments = list(sys.argv if argv is None else argv)
    app = QGuiApplication(arguments)
    app.setApplicationName("Be More Agent Qt Shell")

    catalog_result = configured_menu_catalog()
    catalog = catalog_result.catalog
    controller = QtFaceController(menu_catalog=catalog)
    runtime_menu = RuntimeMenuCoordinator(
        lambda: catalog,
        launch_mode=lambda name: print(
            f"[QT MENU] launch request: owner=mode name={name}",
            flush=True,
        ),
        launch_feature=lambda name: print(
            f"[QT MENU] launch request: owner=feature name={name}",
            flush=True,
        ),
    )
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bmoUi", controller)
    controller.exitRequested.connect(app.quit)
    controller.menuRequested.connect(
        lambda: print("[QT MENU] opened", flush=True)
    )
    controller.menuSelectionRequested.connect(runtime_menu.dispatch)
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
        f"Qt/QML face shell: platform={app.platformName()} qml={QML_PATH} "
        f"configured_items={len(catalog.items)} "
        f"metadata_failures={len(catalog_result.failures)}",
        flush=True,
    )
    return app.exec()


def run_qt_application(argv: Sequence[str] | None = None) -> int:
    """Run the complete assistant with Qt Quick as its only GUI toolkit."""
    arguments = list(sys.argv if argv is None else argv)
    app = QGuiApplication(arguments)
    app.setApplicationName("Be More Agent")
    typed_debug = "--typed" in arguments

    controller = QtFaceController()
    controller.set_typed_input_visible(typed_debug)
    presentation = QtRuntimePresentation(controller)
    view_host = QtViewHost(controller)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bmoUi", controller)
    engine.quit.connect(app.quit)
    engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
    if not engine.rootObjects():
        controller.stop()
        print(f"Could not load QML application: {QML_PATH}", flush=True)
        return 1

    runtime_box: dict[str, object] = {}
    closing = False
    quiet_hours_timer = QTimer()
    quiet_hours_timer.setInterval(1000)

    def runtime() -> object | None:
        return runtime_box.get("runtime")

    def initialize_runtime() -> None:
        if runtime() is not None:
            return
        try:
            from bmo.runtime import AssistantRuntime

            assistant = AssistantRuntime(presentation, view_host)
            runtime_box["runtime"] = assistant
            controller.set_menu_catalog(assistant.menu_catalog)
            controller.set_state(BotStates.IDLE, "Starting assistant services...")
            assistant.check_quiet_hours()
            assistant.start()
            quiet_hours_timer.timeout.connect(assistant.check_quiet_hours)
            quiet_hours_timer.start()
            print(
                "Qt/QML assistant: "
                f"platform={app.platformName()} qml={QML_PATH} "
                f"menu_items={len(assistant.menu_catalog.items)} "
                f"mode_failures={len(assistant.mode_failures)}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"Could not start assistant runtime: {type(exc).__name__}: {exc}",
                flush=True,
            )
            controller.set_state(BotStates.ERROR, f"Startup failed: {str(exc)[:50]}")

    def dispatch_menu(request: object) -> None:
        assistant = runtime()
        if assistant is not None:
            assistant.dispatch_menu(request)  # type: ignore[attr-defined]

    def toggle_ptt() -> None:
        assistant = runtime()
        if assistant is not None:
            assistant.toggle_ptt()  # type: ignore[attr-defined]

    def interrupt() -> None:
        assistant = runtime()
        if assistant is not None:
            assistant.interrupt()  # type: ignore[attr-defined]

    def acknowledge_attention() -> None:
        assistant = runtime()
        if assistant is not None:
            assistant.acknowledge_attention()  # type: ignore[attr-defined]

    def unlock_quiet_hours(passcode: str) -> None:
        assistant = runtime()
        accepted = bool(
            assistant is not None
            and assistant.unlock_quiet_hours(passcode)  # type: ignore[attr-defined]
        )
        controller.quietPinResult(accepted)

    def submit_text(text: str) -> None:
        assistant = runtime()
        if assistant is not None:
            assistant.submit_text(text)  # type: ignore[attr-defined]

    def shutdown() -> None:
        nonlocal closing
        if closing:
            return
        closing = True
        quiet_hours_timer.stop()
        assistant = runtime()
        if assistant is not None:
            assistant.close()  # type: ignore[attr-defined]
        view_host.close()
        controller.stop()

    controller.menuSelectionRequested.connect(dispatch_menu)
    controller.pushToTalkRequested.connect(toggle_ptt)
    controller.interruptRequested.connect(interrupt)
    controller.attentionRequested.connect(acknowledge_attention)
    controller.quietPinSubmitted.connect(unlock_quiet_hours)
    controller.typedInputRequested.connect(submit_text)
    controller.exitRequested.connect(app.quit)
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(0, initialize_runtime)
    return app.exec()


__all__ = [
    "QML_PATH",
    "configured_menu_catalog",
    "preview_menu_catalog",
    "run_qt_application",
    "run_qt_face_shell",
]
