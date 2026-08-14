"""UI-neutral model logging and typed tool-result presentation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import time

from bmo.archive import InteractionArchive
from bmo.features.contracts import (
    ToolAttachmentKind,
    ToolFollowUpKind,
    ToolPresentationKind,
    ToolResult,
)
from bmo.state import BotStates


ModelChat = Callable[..., Any]
InteractionProvider = Callable[[], InteractionArchive | None]
SetState = Callable[[str, str], None]
SetThinkingActive = Callable[[bool], None]
SpeakCompleteResponse = Callable[[str, str | None], None]
RememberTurn = Callable[[str, str], None]
RequestVisionFollowUp = Callable[[str, str], None]


class LoggedModelClient:
    """Call a model client while recording request and response metadata."""

    def __init__(
        self,
        chat: ModelChat,
        interaction_provider: InteractionProvider,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, callback in (
            ("chat", chat),
            ("interaction_provider", interaction_provider),
            ("clock", clock),
        ):
            if not callable(callback):
                raise TypeError(f"Model {name} must be callable.")
        self._chat = chat
        self._interaction_provider = interaction_provider
        self._clock = clock

    def __call__(self, **kwargs: Any) -> Any:
        """Call the configured model and retain observable request metadata."""
        interaction = self._interaction_provider()
        started = self._clock()
        if interaction:
            interaction.append_json(
                "output",
                "model_calls.jsonl",
                {"phase": "request", "request": kwargs},
            )
        try:
            response = self._chat(**kwargs)
        except Exception as exc:
            if interaction:
                interaction.append_json(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "error",
                        "error": str(exc),
                        "duration_seconds": self._clock() - started,
                    },
                )
            raise

        if not kwargs.get("stream"):
            if interaction:
                interaction.append_json(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "response",
                        "response": response,
                        "duration_seconds": self._clock() - started,
                    },
                )
            return response

        def logged_stream():
            content_parts: list[str] = []
            try:
                for chunk in response:
                    try:
                        content_parts.append(str(chunk["message"]["content"]))
                    except (KeyError, TypeError):
                        pass
                    yield chunk
            except Exception as exc:
                if interaction:
                    interaction.append_json(
                        "output",
                        "model_calls.jsonl",
                        {
                            "phase": "stream_error",
                            "error": str(exc),
                            "partial_content": "".join(content_parts),
                            "duration_seconds": self._clock() - started,
                        },
                    )
                raise
            else:
                if interaction:
                    interaction.append_json(
                        "output",
                        "model_calls.jsonl",
                        {
                            "phase": "response",
                            "response": {"content": "".join(content_parts)},
                            "duration_seconds": self._clock() - started,
                        },
                    )

        return logged_stream()


class ToolResultPresenter:
    """Present typed tool results without depending on a GUI framework."""

    def __init__(
        self,
        *,
        model_chat: ModelChat,
        model_options: Mapping[str, Any],
        set_state: SetState,
        set_thinking_active: SetThinkingActive,
        speak_complete_response: SpeakCompleteResponse,
        remember_turn: RememberTurn,
        request_vision_follow_up: RequestVisionFollowUp,
    ) -> None:
        callbacks = {
            "model_chat": model_chat,
            "set_state": set_state,
            "set_thinking_active": set_thinking_active,
            "speak_complete_response": speak_complete_response,
            "remember_turn": remember_turn,
            "request_vision_follow_up": request_vision_follow_up,
        }
        for name, callback in callbacks.items():
            if not callable(callback):
                raise TypeError(f"Conversation {name} must be callable.")
        if not isinstance(model_options, Mapping):
            raise TypeError("Conversation model_options must be a mapping.")
        self._model_chat = model_chat
        self._model_options = model_options
        self._set_state = set_state
        self._set_thinking_active = set_thinking_active
        self._speak_complete_response = speak_complete_response
        self._remember_turn = remember_turn
        self._request_vision_follow_up = request_vision_follow_up

    def present(
        self,
        user_text: str,
        tool_result: ToolResult,
        *,
        image_path: str | None,
        model_to_use: str,
        direct: bool,
    ) -> None:
        """Present one result identically for direct and model-routed tools."""
        if tool_result.follow_up is not None:
            follow_up = tool_result.follow_up
            if follow_up.kind is ToolFollowUpKind.VISION:
                self._request_vision_follow_up(
                    user_text,
                    follow_up.attachment.path,
                )
            return

        attachment_image_path = next(
            (
                attachment.path
                for attachment in tool_result.attachments
                if attachment.kind is ToolAttachmentKind.IMAGE
            ),
            None,
        )
        presentation_image_path = attachment_image_path or image_path
        presentation = tool_result.presentation.for_route(direct=direct)
        if presentation.kind is ToolPresentationKind.DIRECT:
            response_text = presentation.user_text or tool_result.content
        else:
            result_text = tool_result.content
            if not result_text:
                return
            self._set_state(BotStates.THINKING, "Reading...")
            self._set_thinking_active(True)
            final_response = self._model_chat(
                model=model_to_use,
                messages=presentation.summary_messages(
                    content=result_text,
                    user_text=user_text,
                ),
                stream=False,
                options=self._model_options,
            )
            response_text = final_response["message"]["content"]
            if presentation.strip_response:
                response_text = response_text.strip()

        if not response_text:
            return

        self._speak_complete_response(response_text, presentation_image_path)
        self._remember_turn(user_text, response_text)
