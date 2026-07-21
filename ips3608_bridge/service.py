"""Localhost bridge server that owns the persistent serial session."""

from __future__ import annotations

import json
import logging
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .device import DeviceError, Measurement


LOG = logging.getLogger(__name__)
ALLOWED_COMMANDS = frozenset({"health", "status", "on", "off", "shutdown"})


@dataclass
class BridgeState:
    started_at: float
    last_measurement: Measurement | None = None
    last_measurement_at: float = 0.0
    last_error: str | None = None
    consecutive_errors: int = 0
    reconnect_count: int = 0
    output_commanded: bool | None = None


class BridgeController:
    def __init__(self, device: Any, poll_interval: float = 1.0) -> None:
        self.device = device
        self.poll_interval = max(0.25, poll_interval)
        self.state = BridgeState(started_at=time.monotonic())
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor: threading.Thread | None = None
        self._shutdown_callback: Callable[[], None] | None = None

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callback = callback

    def start(self) -> None:
        self._refresh_status()
        self._monitor = threading.Thread(
            target=self._monitor_loop,
            name="ips3608-monitor",
            daemon=True,
        )
        self._monitor.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._monitor is not None:
            self._monitor.join(timeout=max(2.0, self.poll_interval + 1.0))
        with self._lock:
            try:
                self.device.close(safe_output_off=True)
            except Exception as exc:
                LOG.warning("safe device close failed: %s", exc)

    def handle(self, command: str) -> dict[str, Any]:
        if command not in ALLOWED_COMMANDS:
            return {
                "ok": False,
                "error": "command_not_allowed",
                "message": f"command {command!r} is not in the switch-safe allowlist",
            }

        if command == "health":
            return self._health_response()
        if command == "status":
            return self._status_response()
        if command == "on":
            return self._output_response(True)
        if command == "off":
            return self._output_response(False)
        if command == "shutdown":
            # Stop the monitor before waiting for its I/O lock, then perform
            # fail-safe device cleanup before acknowledging shutdown.
            self._stop_event.set()
            with self._lock:
                try:
                    self.device.close(safe_output_off=True)
                except Exception as exc:
                    LOG.warning("pre-shutdown device close failed: %s", exc)
            callback = self._shutdown_callback
            if callback is not None:
                threading.Thread(target=callback, daemon=True).start()
            return {"ok": True, "message": "bridge safely released; shutdown requested"}
        raise AssertionError("unreachable command dispatch")

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            self._refresh_status()

    def _ensure_connected(self) -> None:
        if self.device.connected:
            return
        self.device.connect()
        self.state.reconnect_count += 1

    def _refresh_status(self) -> None:
        with self._lock:
            try:
                self._ensure_connected()
                measurement = self.device.read_status()
                self.state.last_measurement = measurement
                self.state.last_measurement_at = time.monotonic()
                self.state.last_error = None
                self.state.consecutive_errors = 0
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.consecutive_errors += 1
                LOG.warning("status refresh failed: %s", exc)
                try:
                    self.device.abandon_connection()
                except Exception:
                    pass

    def _health_response(self) -> dict[str, Any]:
        with self._lock:
            age = self._measurement_age()
            return {
                "ok": True,
                "service": "running",
                "connected": bool(self.device.connected),
                "device_port": self.device.port,
                "uptime_s": round(time.monotonic() - self.state.started_at, 3),
                "measurement_age_s": None if age is None else round(age, 3),
                "consecutive_errors": self.state.consecutive_errors,
                "reconnect_count": self.state.reconnect_count,
                "output_commanded": self.state.output_commanded,
                "last_error": self.state.last_error,
            }

    def _status_response(self) -> dict[str, Any]:
        age = self._measurement_age()
        if age is None or age > max(2.5, self.poll_interval * 2.5):
            self._refresh_status()

        with self._lock:
            if self.state.last_measurement is None:
                return {
                    "ok": False,
                    "error": "device_unavailable",
                    "message": self.state.last_error or "no measurement available",
                }
            return {
                "ok": True,
                "connected": bool(self.device.connected),
                "measurement_age_s": round(self._measurement_age() or 0.0, 3),
                "measurement": self.state.last_measurement.to_dict(),
                "last_error": self.state.last_error,
            }

    def _output_response(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            try:
                self._ensure_connected()
                self.device.set_output(enabled)
                self.state.output_commanded = enabled
                self.state.last_error = None
                return {
                    "ok": True,
                    "output": "on" if enabled else "off",
                    "message": "output command sent",
                }
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.consecutive_errors += 1
                try:
                    self.device.abandon_connection()
                except Exception:
                    pass

                # Retrying ON is intentionally avoided because a failed reply
                # leaves delivery ambiguous. OFF is safe to retry once.
                if not enabled:
                    try:
                        self._ensure_connected()
                        self.device.set_output(False)
                        self.state.output_commanded = False
                        return {
                            "ok": True,
                            "output": "off",
                            "message": "output-off sent after reconnect",
                        }
                    except Exception as retry_exc:
                        self.state.last_error = str(retry_exc)

                return {
                    "ok": False,
                    "error": "output_command_failed",
                    "message": self.state.last_error,
                }

    def _measurement_age(self) -> float | None:
        if not self.state.last_measurement_at:
            return None
        return max(0.0, time.monotonic() - self.state.last_measurement_at)


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(4097)
        if not raw:
            return
        if len(raw) > 4096:
            self._send({"ok": False, "error": "request_too_large"})
            return
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            command = request.get("command")
            if not isinstance(command, str):
                raise ValueError("command must be a string")
            response = self.server.controller.handle(command)  # type: ignore[attr-defined]
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            response = {
                "ok": False,
                "error": "invalid_request",
                "message": str(exc),
            }
        self._send(response)

    def _send(self, response: dict[str, Any]) -> None:
        payload = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(payload.encode("utf-8") + b"\n")


class LocalBridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        controller: BridgeController,
    ) -> None:
        if address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("the safe bridge may listen only on localhost")
        self.controller = controller
        super().__init__(address, _RequestHandler)
        self.controller.set_shutdown_callback(self.shutdown)


def run_service(device: Any, tcp_port: int, poll_interval: float) -> None:
    controller = BridgeController(device, poll_interval=poll_interval)
    with LocalBridgeServer(("127.0.0.1", tcp_port), controller) as server:
        controller.start()
        LOG.info("bridge listening on 127.0.0.1:%s", tcp_port)
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            controller.close()
