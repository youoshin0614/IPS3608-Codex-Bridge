"""Minimal IPS3608 protocol surface.

Only session control, output enable/disable, and read-only telemetry are
implemented. Voltage/current setter registers are intentionally absent.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


REQUEST_HEADER = 0xF1
RESPONSE_HEADER = 0xF0

COMMAND_READ = 0xA1
COMMAND_WRITE_BYTE = 0xB1
COMMAND_SESSION = 0xC1

REGISTER_LIVE = 0xC3
REGISTER_TEMPERATURE = 0xC4
REGISTER_OUTPUT = 0xDB


@dataclass(frozen=True)
class ResponseFrame:
    command: int
    register: int
    payload: bytes


def checksum(register: int, payload: bytes) -> int:
    return (register + len(payload) + sum(payload)) & 0xFF


def packet(command: int, register: int, payload: bytes) -> bytes:
    return bytes(
        [REQUEST_HEADER, command, register, len(payload)]
    ) + payload + bytes([checksum(register, payload)])


def session_packet(connected: bool) -> bytes:
    return packet(COMMAND_SESSION, 0x00, bytes([1 if connected else 0]))


def output_packet(enabled: bool) -> bytes:
    return packet(COMMAND_WRITE_BYTE, REGISTER_OUTPUT, bytes([1 if enabled else 0]))


def live_request() -> bytes:
    return packet(COMMAND_READ, REGISTER_LIVE, b"\x00")


def temperature_request() -> bytes:
    return packet(COMMAND_READ, REGISTER_TEMPERATURE, b"\x00")


def extract_frames(buffer: bytearray) -> list[ResponseFrame]:
    frames: list[ResponseFrame] = []
    while True:
        if len(buffer) < 5:
            return frames
        if buffer[0] != RESPONSE_HEADER:
            del buffer[0]
            continue

        payload_length = buffer[3]
        frame_length = 5 + payload_length
        if len(buffer) < frame_length:
            return frames

        raw = bytes(buffer[:frame_length])
        del buffer[:frame_length]
        payload = raw[4 : 4 + payload_length]
        if raw[-1] != checksum(raw[2], payload):
            continue
        frames.append(ResponseFrame(raw[1], raw[2], payload))


def decode_live(payload: bytes) -> tuple[float, float, float]:
    if len(payload) != 12:
        raise ValueError(f"expected 12 live bytes, got {len(payload)}")
    return struct.unpack("<fff", payload)


def decode_temperature(payload: bytes) -> float:
    if len(payload) != 4:
        raise ValueError(f"expected 4 temperature bytes, got {len(payload)}")
    return struct.unpack("<f", payload)[0]

