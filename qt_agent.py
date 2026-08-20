"""Launch the production Qt/QML assistant."""

from __future__ import annotations

from bmo.qt.app import run_qt_application


def main() -> None:
    print("--- QT/QML SYSTEM STARTING ---", flush=True)
    raise SystemExit(run_qt_application())


if __name__ == "__main__":
    main()
