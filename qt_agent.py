"""Launch the isolated Qt/QML face shell during the GUI migration."""

from __future__ import annotations

from bmo.qt.app import run_qt_face_shell


def main() -> None:
    print("--- QT/QML FACE SHELL STARTING ---", flush=True)
    raise SystemExit(run_qt_face_shell())


if __name__ == "__main__":
    main()
