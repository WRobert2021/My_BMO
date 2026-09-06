"""Continuous bounded incoming discovery and delivery for the BMO lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable

from .relay import MessagesReader, RelayStateError, RelayStateStore
from .relay.live_source import LiveSourceError, disposable_messages_snapshot
from .relay.sender import DeliveryDisposition, RelaySender
from .source_mount import IncomingSourceConfig, ReadOnlySSHFS, SourceMountError


@dataclass(frozen=True, slots=True)
class IncomingDeliveryStatus:
    state: str
    error_code: str | None
    source_mounted: bool
    scanned_rows: int
    delivered_events: int


class IncomingRelayWorker:
    """Own one recoverable mount/poll loop and its durable relay state."""

    def __init__(
        self,
        *,
        source_config: IncomingSourceConfig,
        relay_config: Any,
        receiver_application: Any,
        key_id: str,
        shared_secret: bytes,
        mount: ReadOnlySSHFS | None = None,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.source_config = source_config
        self.relay_config = relay_config
        self.receiver_application = receiver_application
        self.key_id = key_id
        self._shared_secret = shared_secret
        self.mount = mount or ReadOnlySSHFS(source_config)
        self.on_update = on_update
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._status = IncomingDeliveryStatus(
            state="starting",
            error_code=None,
            source_mounted=False,
            scanned_rows=0,
            delivered_events=0,
        )

    def start(self) -> None:
        with self._lock:
            if self._closed or (self._thread is not None and self._thread.is_alive()):
                return
            thread = threading.Thread(
                target=self._run,
                name="imessage-relay-incoming",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def status(self) -> IncomingDeliveryStatus:
        with self._lock:
            status = self._status
        mounted = False
        try:
            mounted = self.mount.mounted
        except Exception:
            pass
        return IncomingDeliveryStatus(
            state=status.state,
            error_code=status.error_code,
            source_mounted=mounted,
            scanned_rows=status.scanned_rows,
            delivered_events=status.delivered_events,
        )

    def run_once(self) -> IncomingDeliveryStatus:
        """Run one bounded cycle; exposed for deterministic lifecycle tests."""

        if self._closed:
            return self.status()
        try:
            messages_root = self.mount.ensure_mounted()
            with RelayStateStore(
                self.relay_config.state_path,
                retry_policy=self.relay_config.retry_policy,
            ) as store:
                cursor = store.source_cursor()
                with disposable_messages_snapshot(messages_root) as snapshot:
                    batch = MessagesReader(
                        snapshot.database_path,
                        messages_root=messages_root,
                    ).scan(
                        after_rowid=cursor,
                        limit=self.source_config.scan_limit,
                    )
                store.commit_scan(batch, expected_after_rowid=cursor)
                delivered = 0
                transport = _ApplicationTransport(self.receiver_application)
                with RelaySender(
                    store=store,
                    transport=transport,
                    key_id=self.key_id,
                    shared_secret=self._shared_secret,
                ) as sender:
                    for _ in range(self.source_config.delivery_limit):
                        result = sender.deliver_once()
                        if result.disposition is DeliveryDisposition.IDLE:
                            break
                        if result.disposition is DeliveryDisposition.ACKNOWLEDGED:
                            delivered += 1
                error_code = "source_parse_issues" if batch.issues else None
                status = IncomingDeliveryStatus(
                    state="active",
                    error_code=error_code,
                    source_mounted=True,
                    scanned_rows=batch.scanned_row_count,
                    delivered_events=delivered,
                )
        except SourceMountError as exc:
            status = IncomingDeliveryStatus(
                "unavailable", exc.code, False, 0, 0
            )
        except LiveSourceError as exc:
            self.mount.close()
            status = IncomingDeliveryStatus(
                "unavailable", exc.code, False, 0, 0
            )
        except RelayStateError:
            status = IncomingDeliveryStatus(
                "unavailable", "relay_state_unavailable", self.mount.mounted, 0, 0
            )
        except (OSError, ValueError):
            status = IncomingDeliveryStatus(
                "unavailable", "incoming_cycle_failed", self.mount.mounted, 0, 0
            )
        except Exception:
            status = IncomingDeliveryStatus(
                "unavailable", "incoming_cycle_failed", False, 0, 0
            )
        with self._lock:
            if not self._closed:
                self._status = status
        self._notify()
        return status

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            thread = self._thread
            self._shared_secret = b""
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        self.mount.close()
        with self._lock:
            self._status = IncomingDeliveryStatus("closed", None, False, 0, 0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.source_config.poll_interval_seconds)

    def _notify(self) -> None:
        callback = self.on_update
        if callback is not None and not self._closed:
            try:
                callback()
            except Exception:
                pass


class _ApplicationTransport:
    def __init__(self, application: Any) -> None:
        self.application = application

    def send(self, *, body: bytes, headers: Any, path: str = "/v1/events", method: str = "POST") -> Any:
        from .relay.sender import TransportResponse

        response = self.application.handle(
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


__all__ = ["IncomingDeliveryStatus", "IncomingRelayWorker"]
