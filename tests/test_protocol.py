import struct

import ips3608_bridge.protocol as protocol

from ips3608_bridge.protocol import (
    COMMAND_READ,
    REGISTER_LIVE,
    RESPONSE_HEADER,
    checksum,
    decode_live,
    extract_frames,
    live_request,
    output_packet,
    session_packet,
)


def test_known_session_packets():
    assert session_packet(True) == bytes.fromhex("F1 C1 00 01 01 02")
    assert session_packet(False) == bytes.fromhex("F1 C1 00 01 00 01")


def test_output_packets_contain_only_switch_register():
    assert output_packet(True) == bytes.fromhex("F1 B1 DB 01 01 DD")
    assert output_packet(False) == bytes.fromhex("F1 B1 DB 01 00 DC")


def test_extract_and_decode_live_frame():
    payload = struct.pack("<fff", 5.0, 0.25, 1.25)
    frame = bytes(
        [RESPONSE_HEADER, COMMAND_READ, REGISTER_LIVE, len(payload)]
    ) + payload + bytes([checksum(REGISTER_LIVE, payload)])
    buffer = bytearray(b"\x99" + frame)

    frames = extract_frames(buffer)

    assert len(frames) == 1
    assert frames[0].register == REGISTER_LIVE
    assert decode_live(frames[0].payload) == (5.0, 0.25, 1.25)
    assert not buffer


def test_live_request_is_read_only():
    assert live_request() == bytes.fromhex("F1 A1 C3 01 00 C4")


def test_setpoint_registers_and_packets_are_not_exposed():
    for name in (
        "REGISTER_SET_VOLTAGE",
        "REGISTER_SET_CURRENT",
        "set_voltage_packet",
        "set_current_packet",
    ):
        assert not hasattr(protocol, name)
