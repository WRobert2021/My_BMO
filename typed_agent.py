"""Debug launcher that accepts typed BMO commands on the face screen."""

from __future__ import annotations

import threading
import time
import traceback
import tkinter as tk
from queue import Empty, Queue

from bmo.app import BotGUI
from bmo.state import BotStates


class TypedBotGUI(BotGUI):
    """Run the normal BMO application with typed rather than spoken input."""

    def __init__(self, master: tk.Tk) -> None:
        self.typed_input_queue: Queue[str] = Queue()
        super().__init__(master)
        self._build_typed_input()

    def _build_typed_input(self) -> None:
        """Add a keyboard input bar without replacing the animated face."""
        self.typed_input = tk.Entry(
            self.master,
            font=("Arial", 18),
            bg="white",
            fg="black",
            insertbackground="black",
        )
        self.typed_input.place(x=20, y=425, width=650, height=42)
        self.typed_input.bind("<Return>", self.submit_typed_input)

        self.send_button = tk.Button(
            self.master,
            text="Send",
            font=("Arial", 14, "bold"),
            command=self.submit_typed_input,
        )
        self.send_button.place(x=680, y=425, width=100, height=42)
        self.typed_input.focus_set()

    def submit_typed_input(self, event: tk.Event | None = None) -> str:
        """Send the current entry text to the agent's worker thread."""
        del event
        user_text = self.typed_input.get().strip()
        if user_text:
            self.typed_input.delete(0, tk.END)
            self.typed_input_queue.put(user_text)
        self.typed_input.focus_set()
        return "break"

    def _wait_for_typed_input(self) -> str | None:
        while not self.exiting:
            try:
                return self.typed_input_queue.get(timeout=0.1)
            except Empty:
                continue
        return None

    def safe_main_execution(self) -> None:
        try:
            self.warm_up_logic()
            self.tts_thread = threading.Thread(
                target=self._tts_worker,
                name="bmo-tts",
                daemon=True,
            )
            self.tts_thread.start()

            print("Typed on-screen debug input is ready.", flush=True)
            while not self.exiting:
                while self.matching_game_active.is_set() and not self.exiting:
                    time.sleep(0.1)
                if self.exiting:
                    return

                self.set_state(BotStates.IDLE, "Type a command below...")
                user_text = self._wait_for_typed_input()

                if self.exiting or user_text is None:
                    return
                if user_text.lower() == "/quit":
                    self.master.after(0, self.safe_exit)
                    return
                if not user_text:
                    continue

                self._start_interaction("TYPED")
                if self.current_interaction:
                    self.current_interaction.write_text(
                        "input",
                        "transcript.txt",
                        user_text + "\n",
                    )
                    self.current_interaction.event(
                        "typed_input_received",
                        {"text": user_text},
                    )

                self.append_to_text(f"YOU: {user_text}")
                self.interrupted.clear()
                self.chat_and_respond(user_text)
                self._finish_interaction("completed")
        except Exception as exc:
            self._finish_interaction("error", str(exc))
            if not self.exiting:
                traceback.print_exc()
                self.set_state(BotStates.ERROR, f"Fatal Error: {str(exc)[:40]}")


def main() -> None:
    print("--- SYSTEM STARTING (TYPED DEBUG MODE) ---", flush=True)
    root = tk.Tk()
    TypedBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
