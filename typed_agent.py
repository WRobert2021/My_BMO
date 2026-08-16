"""Debug launcher that accepts typed BMO commands on the face screen."""

from __future__ import annotations

import tkinter as tk
from queue import Empty, Queue

from bmo.app import BotGUI
from bmo.modes import InputPolicyKind
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
            menu_event = getattr(self, "menu_action_event", None)
            if menu_event is not None and menu_event.is_set():
                return ""
            try:
                return self.typed_input_queue.get(timeout=0.1)
            except Empty:
                continue
        return None

    def safe_main_execution(self) -> None:
        self._run_runtime_worker(
            self._run_typed_interaction,
            after_initialize=lambda: print(
                "Typed on-screen debug input is ready.",
                flush=True,
            ),
        )

    def _run_typed_interaction(self) -> bool:
        """Run one typed-loop iteration, returning false when it should stop."""
        if self._start_pending_menu_action():
            return True
        while (
            self.mode_registry.input_policy().kind
            == InputPolicyKind.SUSPENDED
            and not self.exiting
        ):
            self.shutdown_event.wait(0.1)
        if self.exiting:
            return False

        self.set_state(BotStates.IDLE, "Type a command below...")
        user_text = self._wait_for_typed_input()

        if self._start_pending_menu_action():
            return True

        if self.exiting or user_text is None:
            return False
        if user_text.lower() == "/quit":
            self._dispatch_ui(self.safe_exit)
            return False
        if not user_text:
            return True

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
        return True


def main() -> None:
    print("--- SYSTEM STARTING (TYPED DEBUG MODE) ---", flush=True)
    root = tk.Tk()
    TypedBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
