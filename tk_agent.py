"""Explicit legacy Tk launcher retained as a migration fallback."""

from __future__ import annotations

import tkinter as tk

from bmo.app import BotGUI


def main() -> None:
    print("--- LEGACY TK SYSTEM STARTING ---", flush=True)
    root = tk.Tk()
    BotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
