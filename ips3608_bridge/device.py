"""Persistent serial transport and a hardware-free simulator."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import serial

from .protocol import (
    COMMAND_READ,
    REGISTER_LIVE,
    REGISTER_TEMPERATURE,
    decode_live,
    decode_temperature,
    extract_frames,
    live_request,
    output_packet,
    session_packet,
    temperature_request,
)
from .diagnostics import classify_error


class DeviceError(RuntimeError):
    """Raised when the physical device cannot complete a safe operation."""


@dataclass(frozen=True)
class Measurement:
    timestamp: str
    voltage_v: float
    current_a: float
    power_w: float
    temperature_c: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SerialFactory = Callable[..., Any]


class IPS3608Device:
    """Own one long-lived serial connection to an IPS3608."""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        read_timeout: float = 0.2,
        serial_factory: SerialFactory = serial.Serial,
        min_write_gap: float = 0.25,
        temperature_interval: float | None = None,
        stabilization_delay: float = 3.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._serial_factory = serial_factory
        self._serial: Any | None = None
        self._io_lock = threading.RLock()
        self._receive_buffer = bytearray()
        self._last_temperature: float | None = None
        self._min_write_gap = max(0.0, min_write_gap)
        self._last_write_at = 0.0
        # Temperature telemetry is optional and requires an additional serial
        # transaction.  Disable it by default to keep the CDC traffic minimal.
        self._temperature_interval = (
            None if temperature_interval is None else max(1.0, temperature_interval)
        )
        self._last_temperature_at = 0.0
        self.stabilization_delay = max(0.0, stabilization_delay)

    @property
    def connected(self) -> bool:
        return bool(self._serial is not None and self._serial.is_open)

    def connect(self, attempts: int = 3) -> None:
        with self._io_lock:
            if self.connected:
                return

            last_error: BaseException | None = None
            attempts_made = 0
            for attempt in range(max(1, attempts)):
                attempts_made += 1
                try:
                    self._raw_close()
                    self._serial = self._new_serial(dtr=True, rts=True)
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()
                    self._receive_buffer.clear()
                    self._write(session_packet(True))
                    time.sleep(0.12)
                    # A successful open is not enough on the flaky Windows CDC
                    # driver. Validate that the device can actually answer.
                    frame = self._query(
                        live_request(), COMMAND_READ, REGISTER_LIVE, timeout=0.8
                    )
                    decode_live(frame.payload)
                    return
                except Exception as exc:
                    last_error = exc
                    self._raw_close()
                    if classify_error(exc).requires_manual_recovery:
                        break
                    if attempt + 1 < max(1, attempts):
                        # Error 31/995 means the Windows USB stack needs time
                        # to tear down the failed endpoint before another open.
                        time.sleep(1.0 * (attempt + 1))
                        self._prime_port()

            raise DeviceError(
                f"unable to connect to {self.port} after {attempts_made} "
                f"attempts: {last_error}"
            ) from last_error

    def read_status(self) -> Measurement:
        with self._io_lock:
            self._require_connection()
            try:
                live = self._query(
                    live_request(), COMMAND_READ, REGISTER_LIVE, timeout=0.8
                )
                voltage, current, device_power = decode_live(live.payload)

                if self._temperature_interval is not None and (
                    self._last_temperature is None
                    or time.monotonic() - self._last_temperature_at
                    >= self._temperature_interval
                ):
                    try:
                        temp_frame = self._query(
                            temperature_request(),
                            COMMAND_READ,
                            REGISTER_TEMPERATURE,
                            timeout=0.6,
                        )
                        self._last_temperature = decode_temperature(temp_frame.payload)
                        self._last_temperature_at = time.monotonic()
                    except DeviceError as exc:
                        if not str(exc).startswith("timeout waiting for register"):
                            raise
                temperature = self._last_temperature

                return Measurement(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    voltage_v=voltage,
                    current_a=current,
                    power_w=device_power,
                    temperature_c=temperature,
                )
            except (OSError, serial.SerialException, ValueError) as exc:
                raise DeviceError(f"status read failed: {exc}") from exc

    def set_output(self, enabled: bool) -> None:
        with self._io_lock:
            self._require_connection()
            try:
                self._write(output_packet(enabled))
                time.sleep(0.1)
            except (OSError, serial.SerialException) as exc:
                raise DeviceError(f"output command failed: {exc}") from exc

    def force_safe_start(self) -> None:
        """Every new serial session begins by commanding output off."""
        self.set_output(False)

    def close(self, safe_output_off: bool = True) -> None:
        with self._io_lock:
            if not self.connected:
                self._raw_close()
                return
            if safe_output_off:
                try:
                    self._write(output_packet(False))
                    time.sleep(0.05)
                except Exception:
                    pass
            try:
                self._write(session_packet(False))
                time.sleep(0.05)
            except Exception:
                pass
            self._raw_close()

    def abandon_connection(self) -> None:
        """Close a broken local handle without sending protocol commands."""
        with self._io_lock:
            self._raw_close()

    def _new_serial(self, dtr: bool, rts: bool) -> Any:
        port = self._serial_factory(
            port=None,
            baudrate=self.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            # The IPS3608 Windows CDC driver can wedge after repeated
            # overlapped read cancellations. Poll queued bytes instead of
            # issuing a 64-byte blocking read for each shorter reply frame.
            timeout=0.0,
            write_timeout=2.0,
            rtscts=False,
            dsrdtr=False,
        )
        port.dtr = dtr
        port.rts = rts
        port.port = self.port
        port.open()
        return port

    def _prime_port(self) -> None:
        """Recover from the IPS3608 Windows driver's intermittent error 995."""
        primer = None
        try:
            primer = self._new_serial(dtr=False, rts=False)
        except (OSError, serial.SerialException):
            pass
        finally:
            if primer is not None and primer.is_open:
                primer.close()
        time.sleep(0.5)

    def _query(
        self,
        request: bytes,
        expected_command: int,
        expected_register: int,
        timeout: float,
    ) -> Any:
        try:
            self._write(request)
        except Exception as exc:
            raise DeviceError(
                f"request write failed for register 0x{expected_register:02X}: {exc}"
            ) from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = self._serial.read(64)
            except (OSError, serial.SerialException) as exc:
                raise DeviceError(f"serial read failed: {exc}") from exc
            if not chunk:
                time.sleep(0.01)
                continue
            self._receive_buffer.extend(chunk)
            for frame in extract_frames(self._receive_buffer):
                if (
                    frame.command == expected_command
                    and frame.register == expected_register
                ):
                    return frame
        raise DeviceError(
            f"timeout waiting for register 0x{expected_register:02X}"
        )

    def _write(self, data: bytes) -> None:
        self._require_connection()
        delay = self._min_write_gap - (time.monotonic() - self._last_write_at)
        if delay > 0:
            time.sleep(delay)
        try:
            written = self._serial.write(data)
        finally:
            self._last_write_at = time.monotonic()
        if written != len(data):
            raise DeviceError(f"short serial write: wrote {written} of {len(data)} bytes")
        self._serial.flush()

    def _require_connection(self) -> None:
        if not self.connected:
            raise DeviceError("device is not connected")

    def _raw_close(self) -> None:
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None
        self._receive_buffer.clear()
        self._last_write_at = 0.0


class SimulatedDevice:
    """Switch-only simulator used for development and integration tests."""

    def __init__(self, port: str = "SIMULATED") -> None:
        self.port = port
        self.connected = False
        self.output_enabled = False
        self.connect_count = 0
        self._temperature = 31.0
        self.stabilization_delay = 0.0

    def connect(self, attempts: int = 3) -> None:
        del attempts
        if not self.connected:
            self.connect_count += 1
            self.connected = True

    def read_status(self) -> Measurement:
        if not self.connected:
            raise DeviceError("simulated device is not connected")
        if self.output_enabled:
            voltage = 5.0 + random.uniform(-0.02, 0.02)
            current = 0.25 + random.uniform(-0.01, 0.01)
            self._temperature = min(45.0, self._temperature + 0.02)
        else:
            voltage = random.uniform(0.0, 0.02)
            current = 0.0
            self._temperature = max(30.0, self._temperature - 0.01)
        return Measurement(
            timestamp=datetime.now(timezone.utc).isoformat(),
            voltage_v=voltage,
            current_a=current,
            power_w=voltage * current,
            temperature_c=self._temperature,
        )

    def set_output(self, enabled: bool) -> None:
        if not self.connected:
            raise DeviceError("simulated device is not connected")
        self.output_enabled = enabled

    def force_safe_start(self) -> None:
        self.set_output(False)

    def close(self, safe_output_off: bool = True) -> None:
        if safe_output_off:
            self.output_enabled = False
        self.connected = False

    def abandon_connection(self) -> None:
        self.connected = False
