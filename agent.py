# =========================================================================
#  Be More Agent 🤖
#  A Local, Offline-First AI Agent for Raspberry Pi
#
#  Copyright (c) 2026 brenpoly
#  Licensed under the MIT License
#  Source: https://github.com/brenpoly/be-more-agent
# =========================================================================

from bmo.qt.app import run_qt_application


def main() -> None:
    print("--- SYSTEM STARTING ---", flush=True)
    raise SystemExit(run_qt_application())


if __name__ == "__main__":
    main()
