"""Qt debug launcher that accepts typed BMO commands on the face screen."""

from __future__ import annotations

from bmo.qt.app import run_qt_application


def __getattr__(name: str):
    """Lazily expose the historical test adapter without polluting Qt imports."""
    if name == "TypedBotGUI":
        from bmo.typed_tk import TypedBotGUI

        return TypedBotGUI
    raise AttributeError(name)


def main() -> None:
    print("--- SYSTEM STARTING (TYPED DEBUG MODE) ---", flush=True)
    raise SystemExit(run_qt_application(["typed_agent.py", "--typed"]))


if __name__ == "__main__":
    main()
