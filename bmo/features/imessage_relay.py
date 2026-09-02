"""Opt-in BMO lifecycle and status UI for the iMessage Relay service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
from iphone_relay import (
    MessagesReader,
    RelayStateError,
    RelayStateStore,
    StateConfigError,
    load_state_config,
)
from iphone_relay.live_source import LiveSourceError, disposable_messages_snapshot
from iphone_relay.reconciliation import (
    ReconciliationError,
    ReconciliationReport,
    ReconciliationWindow,
    RelayReconciler,
)
from iphone_relay.sender import TransportResponse
from kiosk_receiver import (
    ReceiverConfigError,
    ReceiverStateStore,
    ReceiverStoreError,
    build_server,
    load_receiver_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMESSAGE_RELAY_MENU_ITEM = FeatureMenuItem(
    name="imessage_relay",
    label="iMessage Relay",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "micro_sd.png",
)
DEFAULT_RECEIVER_CONFIG_PATH = Path("config/imessage_receiver.json")
DEFAULT_RELAY_CONFIG_PATH = Path("config/imessage_relay.json")
DEFAULT_RECENT_DAYS = 7
MAX_RECENT_DAYS = 31

StatusCallback = Callable[[], None]
RelayAppFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RelayFeatureConfig:
    """Resource-free paths and bounds supplied by the feature entry."""

    receiver_config_path: Path
    relay_config_path: Path
    messages_root: Path | None
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


def load_feature_config(settings: Mapping[str, Any]) -> RelayFeatureConfig:
    """Validate only feature-owned settings without opening any resource."""

    if not isinstance(settings, Mapping):
        raise TypeError("iMessage Relay settings must be an object")
    receiver_path = _path_setting(
        settings,
        "receiver_config_path",
        DEFAULT_RECEIVER_CONFIG_PATH,
    )
    relay_path = _path_setting(
        settings,
        "relay_config_path",
        DEFAULT_RELAY_CONFIG_PATH,
    )
    messages_value = settings.get("messages_root")
    if messages_value is None:
        messages_root = None
    else:
        messages_root = _path_value(messages_value, "messages_root")
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
        relay_config_path=relay_path,
        messages_root=messages_root,
        reconciliation_recent_days=recent_days,
    )


class _ReceiverApplicationTransport:
    """Reuse the authenticated protocol without another loopback connection."""

    def __init__(self, application: Any) -> None:
        self._application = application

    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
        method: str = "POST",
    ) -> TransportResponse:
        response = self._application.handle(
            method=method,
            path=path,
            headers=headers,
            body=body,
        )
        return TransportResponse(
            response.status_code,
            {"Content-Type": "application/json"},
            response.body,
        )

    def close(self) -> None:
        return


class RelayRuntimeService:
    """Own the optional receiver listener and one on-demand reconcile job."""

    def __init__(self, config: RelayFeatureConfig) -> None:
        if not isinstance(config, RelayFeatureConfig):
            raise TypeError("config must be RelayFeatureConfig")
        self.config = config
        self._lock = threading.RLock()
        self._closed = False
        self._server: Any | None = None
        self._receiver_store: ReceiverStateStore | None = None
        self._server_thread: threading.Thread | None = None
        self._job_thread: threading.Thread | None = None
        self._service_state = "unavailable"
        self._service_error_code: str | None = None
        self._reconciliation_state = "idle"
        self._reconciliation_error_code: str | None = None
        self._last_reconciliation: dict[str, int | str] | None = None
        self._relay_config: Any | None = None
        self._key_id: str | None = None
        self._shared_secret: bytes | None = None
        self._start_receiver()
        self._load_relay_config()

    def _start_receiver(self) -> None:
        server: Any | None = None
        store: ReceiverStateStore | None = None
        try:
            receiver_config = load_receiver_config(
                self.config.receiver_config_path,
            )
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
            self._key_id = receiver_config.key_id
            self._shared_secret = receiver_config.shared_secret
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

    def _load_relay_config(self) -> None:
        try:
            if (
                self.config.relay_config_path.is_symlink()
                or not self.config.relay_config_path.is_file()
            ):
                raise StateConfigError("relay state configuration is unavailable")
            self._relay_config = load_state_config(self.config.relay_config_path)
        except StateConfigError:
            self._reconciliation_error_code = "relay_config_invalid"
        except (OSError, ValueError):
            self._reconciliation_error_code = "relay_config_invalid"

    def status(self) -> RelayRuntimeStatus:
        with self._lock:
            state = self._service_state
            error_code = self._service_error_code
            store = self._receiver_store
            job_running = self._job_thread is not None and self._job_thread.is_alive()
            reconciliation_available = (
                not self._closed
                and state == "available"
                and self._relay_config is not None
                and self.config.messages_root is not None
                and not job_running
            )
            reconciliation_state = self._reconciliation_state
            reconciliation_error = self._reconciliation_error_code
            last_report = (
                None
                if self._last_reconciliation is None
                else dict(self._last_reconciliation)
            )
        received = pending = complete = partial = 0
        if store is not None and state == "available":
            try:
                summary = store.summary()
            except ReceiverStoreError:
                state = "unavailable"
                error_code = "receiver_store_unavailable"
                reconciliation_available = False
            else:
                received = summary.event_count
                pending = summary.pending_event_count
                complete = summary.complete_attachment_count
                partial = summary.partial_attachment_count
        if self.config.messages_root is None and reconciliation_error is None:
            reconciliation_error = "source_not_configured"
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
            last_reconciliation=last_report,
        )

    def reconcile_recent(self, on_complete: StatusCallback | None = None) -> bool:
        window = ReconciliationWindow.recent(
            end_utc=datetime.now(timezone.utc),
            days=self.config.reconciliation_recent_days,
        )
        return self._start_reconciliation(window, on_complete)

    def reconcile_month(
        self,
        year: int,
        month: int,
        on_complete: StatusCallback | None = None,
    ) -> bool:
        window = ReconciliationWindow.calendar_month(year=year, month=month)
        return self._start_reconciliation(window, on_complete)

    def _start_reconciliation(
        self,
        window: ReconciliationWindow,
        on_complete: StatusCallback | None,
    ) -> bool:
        if on_complete is not None and not callable(on_complete):
            raise TypeError("reconciliation completion must be callable")
        with self._lock:
            if (
                self._closed
                or self._service_state != "available"
                or self._server is None
                or self._relay_config is None
                or self._key_id is None
                or self._shared_secret is None
                or self.config.messages_root is None
                or (self._job_thread is not None and self._job_thread.is_alive())
            ):
                return False
            self._reconciliation_state = "running"
            self._reconciliation_error_code = None
            thread = threading.Thread(
                target=self._run_reconciliation,
                args=(window, on_complete),
                name="imessage-relay-reconciliation",
                daemon=True,
            )
            self._job_thread = thread
            try:
                thread.start()
            except Exception:
                self._job_thread = None
                self._reconciliation_state = "failed"
                self._reconciliation_error_code = "reconciliation_start_failed"
                return False
            return True

    def _run_reconciliation(
        self,
        window: ReconciliationWindow,
        on_complete: StatusCallback | None,
    ) -> None:
        report: ReconciliationReport | None = None
        error_code: str | None = None
        try:
            assert self.config.messages_root is not None
            assert self._relay_config is not None
            assert self._key_id is not None
            assert self._shared_secret is not None
            if self.config.messages_root.is_symlink():
                raise LiveSourceError("messages_trio_unreadable")
            with disposable_messages_snapshot(self.config.messages_root) as snapshot:
                with RelayStateStore(
                    self._relay_config.state_path,
                    retry_policy=self._relay_config.retry_policy,
                ) as relay_store:
                    transport = _ReceiverApplicationTransport(
                        self._server.application,
                    )
                    reconciler = RelayReconciler(
                        reader=MessagesReader(
                            snapshot.database_path,
                            messages_root=snapshot.messages_root,
                        ),
                        store=relay_store,
                        transport=transport,
                        key_id=self._key_id,
                        shared_secret=self._shared_secret,
                    )
                    report = reconciler.reconcile(window)
        except LiveSourceError:
            error_code = "source_unavailable"
        except ReconciliationError as exc:
            error_code = exc.code
        except StateConfigError:
            error_code = "relay_config_invalid"
        except RelayStateError:
            error_code = "relay_state_unavailable"
        except (ReceiverStoreError, OSError):
            error_code = "reconciliation_unavailable"
        except Exception:
            error_code = "reconciliation_failed"
        with self._lock:
            if report is not None:
                self._last_reconciliation = _report_mapping(report)
                self._reconciliation_state = "complete"
                self._reconciliation_error_code = None
            else:
                self._reconciliation_state = "failed"
                self._reconciliation_error_code = error_code or "reconciliation_failed"
            closed = self._closed
        if on_complete is not None and not closed:
            try:
                on_complete()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            job_thread = self._job_thread
            server_thread = self._server_thread
            server = self._server
            store = self._receiver_store
            self._service_state = "closed"
            self._key_id = None
            self._shared_secret = None
        if job_thread is not None and job_thread is not threading.current_thread():
            job_thread.join()
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
    """Register and start the explicitly enabled receiver service."""

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
    return _path_value(settings.get(key, default), key)


def _path_value(value: object, key: str) -> Path:
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


def _report_mapping(report: ReconciliationReport) -> dict[str, int | str]:
    values = asdict(report)
    values["window_kind"] = report.window_kind.value
    return values


__all__ = [
    "DEFAULT_RECEIVER_CONFIG_PATH",
    "DEFAULT_RELAY_CONFIG_PATH",
    "IMESSAGE_RELAY_MENU_ITEM",
    "IMessageRelayTool",
    "RelayFeatureConfig",
    "RelayRuntimeService",
    "RelayRuntimeStatus",
    "load_feature_config",
    "register",
    "register_menu_metadata",
    "register_metadata",
]
