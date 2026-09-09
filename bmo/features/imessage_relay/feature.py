"""Opt-in BMO lifecycle and status UI for the iMessage Relay receiver."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
from pathlib import Path
import ssl
import threading
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)
from bmo.view_factory import NOT_HOSTED, create_hosted_view
from .receiver import (
    ReceiverConfigError,
    ReceiverStateStore,
    ReceiverStoreError,
    build_server,
    load_receiver_config,
)
from .phone_control import (
    PhoneControlConfigError,
    PhoneControlCoordinator,
    load_phone_control_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMESSAGE_RELAY_MENU_ITEM = FeatureMenuItem(
    name="imessage_relay",
    label="iMessage Relay",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "message.png",
)
DEFAULT_RECEIVER_CONFIG_PATH = Path("config/imessage_receiver.json")
DEFAULT_PHONE_CONTROL_CONFIG_PATH = Path("config/imessage_phone_control.json")
DEFAULT_RECENT_DAYS = 7
MAX_RECENT_DAYS = 31

StatusCallback = Callable[[], None]
RelayAppFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RelayFeatureConfig:
    """Resource-free receiver settings supplied by the feature entry."""

    receiver_config_path: Path
    phone_control_config_path: Path = DEFAULT_PHONE_CONTROL_CONFIG_PATH
    reconciliation_recent_days: int = DEFAULT_RECENT_DAYS


@dataclass(frozen=True, slots=True)
class RelayRuntimeStatus:
    """Content-free status safe for UI and tests."""

    service_state: str
    service_error_code: str | None
    listening: bool
    received_events: int
    pending_events: int
    complete_attachments: int
    partial_attachments: int
    reconciliation_state: str
    reconciliation_error_code: str | None
    reconciliation_available: bool
    last_reconciliation: Mapping[str, int | str] | None
    incoming_state: str = "unavailable"
    incoming_error_code: str | None = None
    phone_backlog_count: int | None = None


@dataclass(frozen=True, slots=True)
class IncomingFeedItem:
    kind: str
    sender: str
    timestamp: str
    text: str
    attachments: tuple[str, ...]


def load_feature_config(settings: Mapping[str, Any]) -> RelayFeatureConfig:
    """Validate only feature-owned settings without opening a resource."""

    if not isinstance(settings, Mapping):
        raise TypeError("iMessage Relay settings must be an object")
    receiver_path = _path_setting(
        settings,
        "receiver_config_path",
        DEFAULT_RECEIVER_CONFIG_PATH,
    )
    phone_control_path = _path_setting(
        settings,
        "phone_control_config_path",
        DEFAULT_PHONE_CONTROL_CONFIG_PATH,
    )
    recent_days = settings.get("reconciliation_recent_days", DEFAULT_RECENT_DAYS)
    if (
        isinstance(recent_days, bool)
        or not isinstance(recent_days, int)
        or not 1 <= recent_days <= MAX_RECENT_DAYS
    ):
        raise ValueError(
            "iMessage Relay reconciliation_recent_days must be from 1 through 31"
        )
    return RelayFeatureConfig(
        receiver_config_path=receiver_path,
        phone_control_config_path=phone_control_path,
        reconciliation_recent_days=recent_days,
    )


class RelayRuntimeService:
    """Own the kiosk receiver and failure-isolated Stage 12 phone control."""

    def __init__(self, config: RelayFeatureConfig) -> None:
        if not isinstance(config, RelayFeatureConfig):
            raise TypeError("config must be RelayFeatureConfig")
        self.config = config
        self._lock = threading.RLock()
        self._closed = False
        self._server: Any | None = None
        self._receiver_store: ReceiverStateStore | None = None
        self._server_thread: threading.Thread | None = None
        self._phone_control: PhoneControlCoordinator | None = None
        self._phone_control_error_code: str | None = None
        self._service_state = "unavailable"
        self._service_error_code: str | None = None
        self._start_receiver()
        if self._service_state == "available":
            self._start_phone_control()

    def _start_phone_control(self) -> None:
        coordinator: PhoneControlCoordinator | None = None
        try:
            control_config = load_phone_control_config(
                self.config.phone_control_config_path
            )
            coordinator = PhoneControlCoordinator(
                control_config,
                recent_days=self.config.reconciliation_recent_days,
            )
            coordinator.start()
        except PhoneControlConfigError:
            self._phone_control_error_code = "phone_control_config_invalid"
            return
        except (OSError, ssl.SSLError):
            self._phone_control_error_code = "phone_control_start_failed"
            if coordinator is not None:
                coordinator.close()
            return
        except Exception:
            self._phone_control_error_code = "phone_control_start_failed"
            if coordinator is not None:
                coordinator.close()
            return
        self._phone_control = coordinator

    def _start_receiver(self) -> None:
        server: Any | None = None
        store: ReceiverStateStore | None = None
        try:
            receiver_config = load_receiver_config(self.config.receiver_config_path)
            server, store = build_server(receiver_config)
            thread = threading.Thread(
                target=self._serve_receiver,
                args=(server,),
                name="imessage-relay-receiver",
                daemon=True,
            )
            self._server = server
            self._receiver_store = store
            self._server_thread = thread
            thread.start()
        except ReceiverConfigError:
            self._service_error_code = "receiver_config_invalid"
            _close_partial_receiver(server, store)
            return
        except ReceiverStoreError:
            self._service_error_code = "receiver_store_unavailable"
            _close_partial_receiver(server, store)
            return
        except (OSError, ssl.SSLError):
            self._service_error_code = "receiver_start_failed"
            _close_partial_receiver(server, store)
            return
        except Exception:
            self._service_error_code = "receiver_start_failed"
            _close_partial_receiver(server, store)
            return
        self._service_state = "available"

    def _serve_receiver(self, server: Any) -> None:
        try:
            server.serve_forever(poll_interval=0.1)
        except Exception:
            with self._lock:
                if not self._closed:
                    self._service_state = "unavailable"
                    self._service_error_code = "receiver_runtime_failed"

    def status(self) -> RelayRuntimeStatus:
        with self._lock:
            state = self._service_state
            error_code = self._service_error_code
            store = self._receiver_store
            phone_control = self._phone_control
            control_error = self._phone_control_error_code
            closed = self._closed
        received = pending = complete = partial = 0
        if store is not None and state == "available":
            try:
                summary = store.summary()
            except ReceiverStoreError:
                state = "unavailable"
                error_code = "receiver_store_unavailable"
            else:
                received = summary.event_count
                pending = summary.pending_event_count
                complete = summary.complete_attachment_count
                partial = summary.partial_attachment_count
        reconciliation_state = "unavailable"
        reconciliation_error = control_error or "phone_control_config_invalid"
        reconciliation_available = False
        last_reconciliation: Mapping[str, int | str] | None = None
        phone_backlog_count: int | None = None
        phone_state = None
        phone_error = None
        if phone_control is not None and not closed:
            control_status = phone_control.status()
            phone_state = control_status.phone_state
            phone_error = control_status.error_code
            phone_backlog_count = control_status.backlog_count
            reconciliation_state = control_status.reconciliation_state
            reconciliation_error = control_status.reconciliation_error_code
            reconciliation_available = (
                state == "available" and phone_state == "available"
            )
            last_reconciliation = control_status.last_reconciliation

        if closed:
            incoming_state = "closed"
            incoming_error = None
        elif state != "available":
            incoming_state = "unavailable"
            incoming_error = error_code
        elif phone_state == "available":
            incoming_state = "connected"
            incoming_error = None
        elif phone_control is not None:
            incoming_state = "waiting"
            incoming_error = phone_error
        else:
            incoming_state = "ready"
            incoming_error = control_error
        return RelayRuntimeStatus(
            service_state=state,
            service_error_code=error_code,
            listening=state == "available" and store is not None,
            received_events=received,
            pending_events=pending,
            complete_attachments=complete,
            partial_attachments=partial,
            reconciliation_state=reconciliation_state,
            reconciliation_error_code=reconciliation_error,
            reconciliation_available=reconciliation_available,
            last_reconciliation=last_reconciliation,
            incoming_state=incoming_state,
            incoming_error_code=incoming_error,
            phone_backlog_count=phone_backlog_count,
        )

    def recent_items(self, limit: int = 20) -> tuple[IncomingFeedItem, ...]:
        """Return private incoming content only to the dedicated relay view."""

        with self._lock:
            store = self._receiver_store
            closed = self._closed
        if closed or store is None:
            return ()
        try:
            stored = store.recent_events(min(100, max(1, limit * 3)))
            items: list[IncomingFeedItem] = []
            for row in stored:
                raw = row.event_json.encode("utf-8")
                if not hmac.compare_digest(
                    hashlib.sha256(raw).hexdigest(),
                    row.event_digest,
                ):
                    continue
                event = json.loads(row.event_json)
                if not isinstance(event, dict) or event.get("direction") != "incoming":
                    continue
                sender_mapping = event.get("sender")
                sender = (
                    sender_mapping.get("identifier")
                    if isinstance(sender_mapping, dict)
                    else None
                )
                timestamp = event.get("timestamp_utc")
                if not isinstance(timestamp, str):
                    continue
                if event.get("event_kind") == "message":
                    raw_text = event.get("text")
                    text = raw_text.strip() if isinstance(raw_text, str) else ""
                    raw_attachments = event.get("attachments")
                    attachments = tuple(
                        str(attachment.get("media_category"))
                        for attachment in (
                            raw_attachments if isinstance(raw_attachments, list) else []
                        )
                        if isinstance(attachment, dict)
                        and isinstance(attachment.get("media_category"), str)
                    )
                    if not text:
                        text = "Attachment" if attachments else "Message"
                    kind = "message"
                elif event.get("event_kind") in {"reaction_added", "reaction_removed"}:
                    attachments = ()
                    action = (
                        "Removed"
                        if event.get("event_kind") == "reaction_removed"
                        else "Reacted"
                    )
                    reaction = event.get("reaction_kind")
                    if not isinstance(reaction, str):
                        continue
                    text = f"{action}: {reaction.replace('_', ' ')}"
                    kind = "reaction"
                else:
                    continue
                items.append(
                    IncomingFeedItem(
                        kind=kind,
                        sender=(
                            sender
                            if isinstance(sender, str) and sender
                            else "Unknown sender"
                        ),
                        timestamp=timestamp,
                        text=text[:2_000],
                        attachments=attachments,
                    )
                )
                if len(items) >= limit:
                    break
            return tuple(items)
        except Exception:
            return ()

    def reconcile_recent(self, on_complete: StatusCallback | None = None) -> bool:
        if on_complete is not None and not callable(on_complete):
            raise TypeError("reconciliation completion must be callable")
        with self._lock:
            control = self._phone_control
            closed = self._closed
        return False if closed or control is None else control.reconcile_recent(on_complete)

    def reconcile_month(
        self,
        year: int,
        month: int,
        on_complete: StatusCallback | None = None,
    ) -> bool:
        if on_complete is not None and not callable(on_complete):
            raise TypeError("reconciliation completion must be callable")
        datetime(year, month, 1)
        with self._lock:
            control = self._phone_control
            closed = self._closed
        return (
            False
            if closed or control is None
            else control.reconcile_month(year, month, on_complete)
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            server_thread = self._server_thread
            server = self._server
            store = self._receiver_store
            phone_control = self._phone_control
            self._service_state = "closed"
        if phone_control is not None:
            phone_control.close()
        if server is not None:
            if server_thread is not None and server_thread.is_alive():
                server.shutdown()
            server.server_close()
        if server_thread is not None and server_thread is not threading.current_thread():
            server_thread.join(timeout=5)
        if store is not None:
            store.close()


def _create_relay_app(*args: Any, **kwargs: Any) -> Any:
    hosted = create_hosted_view("imessage_relay", args, kwargs)
    if hosted is not NOT_HOSTED:
        return hosted
    raise RuntimeError("iMessage Relay status requires the Qt hosted view")


class IMessageRelayTool:
    """Menu-owned lifecycle anchor for the receiver and status surface."""

    action = "imessage_relay"
    aliases: tuple[str, ...] = ()
    menu_only = True
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        service: RelayRuntimeService,
        *,
        app_factory: RelayAppFactory = _create_relay_app,
        menu_item: FeatureMenuItem = IMESSAGE_RELAY_MENU_ITEM,
    ) -> None:
        self.service = service
        self.menu_item = menu_item
        self._app_factory = app_factory
        self._menu_ui: Any | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            self._menu_ui = None
            context.on_close()

        try:
            self._menu_ui = self._app_factory(
                context.master,
                status_provider=self.service.status,
                feed_provider=self.service.recent_items,
                reconcile_recent=self.service.reconcile_recent,
                reconcile_month=self.service.reconcile_month,
                on_close=handle_close,
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    def close(self) -> None:
        menu = self._menu_ui
        if menu is not None:
            menu.close()
        self.service.close()


class _MetadataTool:
    """Resource-free registry placeholder for metadata-only routing loads."""

    action = "imessage_relay"
    aliases: tuple[str, ...] = ()
    menu_only = True
    menu_item = IMESSAGE_RELAY_MENU_ITEM
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        context.on_close()

    def close(self) -> None:
        return


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register and start the explicitly enabled kiosk receiver."""

    registry.register(IMessageRelayTool(RelayRuntimeService(load_feature_config(settings))))


def register_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register resource-free metadata without reading private config."""

    del settings
    registry.register(_MetadataTool())


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute resource-free menu metadata."""

    del settings
    registry.register(IMESSAGE_RELAY_MENU_ITEM)


def _path_setting(settings: Mapping[str, Any], key: str, default: Path) -> Path:
    value = settings.get(key, default)
    if not isinstance(value, (str, Path)):
        raise TypeError(f"iMessage Relay {key} must be a path string")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"iMessage Relay {key} must not be empty")
    return Path(value).expanduser()


def _close_partial_receiver(
    server: Any | None,
    store: ReceiverStateStore | None,
) -> None:
    if server is not None:
        server.server_close()
    if store is not None:
        store.close()


__all__ = [
    "DEFAULT_PHONE_CONTROL_CONFIG_PATH",
    "DEFAULT_RECEIVER_CONFIG_PATH",
    "IMESSAGE_RELAY_MENU_ITEM",
    "IMessageRelayTool",
    "IncomingFeedItem",
    "RelayFeatureConfig",
    "RelayRuntimeService",
    "RelayRuntimeStatus",
    "load_feature_config",
    "register",
    "register_menu_metadata",
    "register_metadata",
]
