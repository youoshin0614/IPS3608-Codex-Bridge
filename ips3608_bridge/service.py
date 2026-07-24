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
from .diagnostics import ErrorReporter, classify_error, error_details_dict


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
    safety_interlock: bool = False
    safety_interlock_reason: str | None = None
    last_error_kind: str | None = None


class BridgeController:
    def __init__(
        self,
        device: Any,
        poll_interval: float = 0.0,
        output_verify_timeout: float = 3.0,
    ) -> None:
        self.device = device
        self.poll_interval = 0.0 if poll_interval <= 0.0 else max(0.25, poll_interval)
        self.output_verify_timeout = max(0.25, output_verify_timeout)
        self.state = BridgeState(started_at=time.monotonic())
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._priority_off = threading.Event()
        self._monitor: threading.Thread | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._output_enable_ready_at = 0.0
        self._error_reporter = ErrorReporter()

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callback = callback

    def start(self) -> None:
        self._refresh_status()
        if self.poll_interval > 0.0:
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
                self._record_error("safe_device_close_failed", exc)

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
            if self.state.safety_interlock:
                return self._interlock_response("status")
            return self._status_response()
        if command == "on":
            if self.state.safety_interlock:
                return self._interlock_response("on")
            return self._output_response(True)
        if command == "off":
            self._priority_off.set()
            try:
                return self._off_response()
            finally:
                self._priority_off.clear()
        if command == "shutdown":
            return self._shutdown()
        raise AssertionError("unreachable command dispatch")

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            if self._priority_off.is_set():
                continue
            if not self._lock.acquire(timeout=0.1):
                continue
            try:
                if not self._priority_off.is_set():
                    self._refresh_status()
            finally:
                self._lock.release()

    def _shutdown(self) -> dict[str, Any]:
        self._priority_off.set()
        try:
            with self._lock:
                measurement, error = self._recover_and_verify_output_off()
                if error is not None or measurement is None:
                    self.state.output_commanded = None
                    self.state.last_error = error
                    return {
                        "ok": False,
                        "error": "output_off_unverified",
                        "message": (
                            "bridge remains running because output-off could not be "
                            f"verified: {error}"
                        ),
                    }
                self.device.close(safe_output_off=False)
                self.state.output_commanded = False
                self.state.last_error = None
            self._stop_event.set()
            callback = self._shutdown_callback
            if callback is not None:
                threading.Thread(target=callback, daemon=True).start()
            return {
                "ok": True,
                "message": "output-off verified; bridge released; shutdown requested",
            }
        finally:
            self._priority_off.clear()

    def _ensure_connected(
        self, *, safety_operation: bool = False
    ) -> Measurement | None:
        if self.device.connected:
            return None
        if self.state.safety_interlock and not safety_operation:
            raise DeviceError("safety interlock blocks automatic device reconnect")
        self.device.connect(attempts=1 if safety_operation else 3)
        # Use the full automation edition's connection contract: a newly
        # opened session is not usable until OFF is sent and 0 V is observed.
        self.device.force_safe_start()
        verified, measurement, verification_error = self._verify_output_state(False)
        if not verified or measurement is None:
            try:
                self.device.abandon_connection()
            except Exception:
                pass
            raise DeviceError(
                f"reconnect output-off verification failed: {verification_error}"
            )
        self.state.reconnect_count += 1
        self.state.output_commanded = False
        self._output_enable_ready_at = time.monotonic() + float(
            getattr(self.device, "stabilization_delay", 0.0)
        )
        return measurement

    def _refresh_status(self) -> None:
        with self._lock:
            try:
                self._ensure_connected()
                measurement = self.device.read_status()
                self.state.last_measurement = measurement
                self.state.last_measurement_at = time.monotonic()
                self.state.last_error = None
                self.state.last_error_kind = None
                self.state.consecutive_errors = 0
            except Exception as exc:
                self._record_error(
                    "status_refresh_failed",
                    exc,
                    force_unknown=True,
                )
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
                "output_state": self._output_state(),
                "safety_interlock": self.state.safety_interlock,
                "safety_interlock_reason": self.state.safety_interlock_reason,
                "last_error_kind": self.state.last_error_kind,
                "telemetry_mode": (
                    "on_demand" if self.poll_interval == 0.0 else "background"
                ),
                "poll_interval_s": self.poll_interval,
                "last_error": self.state.last_error,
            }

    def _status_response(self) -> dict[str, Any]:
        age = self._measurement_age()
        cache_horizon = max(15.0, self.poll_interval * 2.5)
        if age is None or age > cache_horizon:
            self._refresh_status()

        with self._lock:
            if self.state.last_measurement is None or not self.device.connected:
                return {
                    "ok": False,
                    "error": "device_unavailable",
                    "message": self.state.last_error or "no measurement available",
                    "output_state": self._output_state(),
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
                if enabled:
                    remaining = self._output_enable_ready_at - time.monotonic()
                    if remaining > 0.0:
                        time.sleep(remaining)
                self.device.set_output(enabled)
                verified, measurement, verification_error = self._verify_output_state(
                    enabled
                )
                if not verified:
                    if enabled:
                        # Never retry an ambiguous ON. Prove a safe OFF or
                        # report the physical output state as unknown.
                        _safe_measurement, safe_off_error = (
                            self._recover_and_verify_output_off()
                        )
                        self.state.output_commanded = (
                            False if safe_off_error is None else None
                        )
                        if safe_off_error:
                            verification_error = (
                                f"{verification_error}; safe-off error: "
                                f"{safe_off_error}"
                            )
                    else:
                        measurement, safe_off_error = (
                            self._recover_and_verify_output_off()
                        )
                        verified = safe_off_error is None
                        if safe_off_error:
                            verification_error = safe_off_error
                    if not verified:
                        self._record_error(
                            "output_verification_failed",
                            verification_error,
                        )
                        return {
                            "ok": False,
                            "error": "output_verification_failed",
                            "message": verification_error,
                        }
                self.state.output_commanded = enabled
                self.state.last_error = None
                self.state.last_error_kind = None
                return {
                    "ok": True,
                    "output": "on" if enabled else "off",
                    "message": "output command verified by voltage telemetry",
                    "verified_voltage_v": (
                        None if measurement is None else measurement.voltage_v
                    ),
                }
            except Exception as exc:
                self._record_error(
                    "output_command_failed",
                    exc,
                    force_unknown=True,
                )
                try:
                    self.device.abandon_connection()
                except Exception:
                    pass

                # Retrying ON is intentionally avoided because a failed reply
                # leaves delivery ambiguous. OFF is safe to retry and verify.
                measurement, safe_off_error = self._recover_and_verify_output_off()
                if safe_off_error is None and measurement is not None:
                    self.state.output_commanded = False
                    if not enabled:
                        return {
                            "ok": True,
                            "output": "off",
                            "message": "output-off verified after reconnect",
                            "verified_voltage_v": measurement.voltage_v,
                        }
                elif enabled:
                    self.state.output_commanded = None
                    self.state.last_error = (
                        f"output-on command failed: {exc}; safe-off error: "
                        f"{safe_off_error}"
                    )
                else:
                    self.state.last_error = safe_off_error

                return {
                    "ok": False,
                    "error": "output_command_failed",
                    "message": self.state.last_error,
                }

    def _off_response(self) -> dict[str, Any]:
        """Use one bounded safety path for OFF, including while interlocked."""
        with self._lock:
            measurement, error = self._recover_and_verify_output_off()
            if error is not None or measurement is None:
                return {
                    "ok": False,
                    "error": "output_off_unverified",
                    "message": error,
                    "output_state": "unknown",
                    "safety_interlock": self.state.safety_interlock,
                }
            return {
                "ok": True,
                "output": "off",
                "message": "output-off verified by voltage telemetry",
                "verified_voltage_v": measurement.voltage_v,
            }

    def _recover_and_verify_output_off(
        self,
    ) -> tuple[Measurement | None, str | None]:
        last_error = "output-off was not attempted"
        for attempt in range(2):
            try:
                safe_start_measurement = self._ensure_connected(
                    safety_operation=True
                )
                if safe_start_measurement is not None:
                    self.state.output_commanded = False
                    self._clear_safety_interlock()
                    return safe_start_measurement, None
                self.device.set_output(False)
                verified, measurement, verification_error = (
                    self._verify_output_state(False)
                )
                if verified and measurement is not None:
                    self.state.output_commanded = False
                    self._clear_safety_interlock()
                    return measurement, None
                last_error = verification_error
            except Exception as exc:
                last_error = str(exc)
            try:
                self.device.abandon_connection()
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.75)
        self._record_error(
            "output_off_unverified",
            last_error,
            force_unknown=True,
            latch_interlock=True,
        )
        return None, last_error

    def _verify_output_state(
        self,
        enabled: bool,
    ) -> tuple[bool, Measurement | None, str]:
        deadline = time.monotonic() + self.output_verify_timeout
        last_measurement: Measurement | None = None
        last_error = "no telemetry was received"
        while time.monotonic() < deadline:
            try:
                last_measurement = self.device.read_status()
                self.state.last_measurement = last_measurement
                self.state.last_measurement_at = time.monotonic()
                voltage = float(last_measurement.voltage_v)
                if enabled and voltage > 0.1:
                    return True, last_measurement, ""
                if not enabled and voltage <= 0.1:
                    return True, last_measurement, ""
                last_error = (
                    f"output did not turn {'on' if enabled else 'off'}: "
                    f"measured {voltage:.3f} V"
                )
            except Exception as exc:
                last_error = f"output verification telemetry failed: {exc}"
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.2, remaining))
        return False, last_measurement, last_error

    def _record_error(
        self,
        event: str,
        exc: BaseException | str,
        *,
        force_unknown: bool = False,
        latch_interlock: bool = False,
    ) -> None:
        details = classify_error(exc)
        self.state.last_error = str(exc)
        self.state.last_error_kind = details.kind
        self.state.consecutive_errors += 1
        if force_unknown or details.requires_manual_recovery:
            self.state.output_commanded = None
        if details.requires_manual_recovery or latch_interlock:
            self.state.safety_interlock = True
            self.state.safety_interlock_reason = (
                details.action
                if details.requires_manual_recovery
                else "Output-off was not verified. Reset the USB path and run OFF."
            )
        self._error_reporter.report(
            LOG,
            event,
            exc,
            output_state=self._output_state(),
            safety_interlock=self.state.safety_interlock,
            device_port=str(self.device.port),
        )

    def _clear_safety_interlock(self) -> None:
        if self.state.safety_interlock:
            LOG.info(
                "safety interlock cleared after output-off verification",
                extra={"event": "safety_interlock_cleared"},
            )
        self.state.safety_interlock = False
        self.state.safety_interlock_reason = None
        self.state.last_error = None
        self.state.last_error_kind = None
        self.state.consecutive_errors = 0

    def _output_state(self) -> str:
        if self.state.output_commanded is True:
            return "on"
        if self.state.output_commanded is False:
            return "off"
        return "unknown"

    def _interlock_response(self, command: str) -> dict[str, Any]:
        details = classify_error(self.state.last_error or "device error")
        return {
            "ok": False,
            "error": "safety_interlock_active",
            "message": (
                f"{command} blocked because output state is unknown after "
                f"{self.state.last_error_kind or 'a transport fault'}; "
                "change the physical USB path and run OFF"
            ),
            "output_state": "unknown",
            "safety_interlock": True,
            "recovery": error_details_dict(details),
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
