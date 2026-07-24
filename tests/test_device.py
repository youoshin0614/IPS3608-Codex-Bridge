import struct

import pytest

from ips3608_bridge.device import IPS3608Device
from ips3608_bridge.protocol import (
    COMMAND_READ,
    REGISTER_LIVE,
    REGISTER_TEMPERATURE,
    RESPONSE_HEADER,
    checksum,
    live_request,
    output_packet,
    temperature_request,
)


def response(register: int, payload: bytes) -> bytes:
    return bytes(
        [RESPONSE_HEADER, COMMAND_READ, register, len(payload)]
    ) + payload + bytes([checksum(register, payload)])


class FakeSerial:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.port = None
        self.dtr = None
        self.rts = None
        self.is_open = False
        self.writes = []
        self.rx = bytearray()
        self.open_count = 0

    def open(self):
        self.open_count += 1
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        self.rx.clear()

    def reset_output_buffer(self):
        pass

    def write(self, data: bytes):
        self.writes.append(data)
        if data == live_request():
            self.rx.extend(
                response(REGISTER_LIVE, struct.pack("<fff", 5.0, 0.25, 1.25))
            )
        elif data == temperature_request():
            self.rx.extend(response(REGISTER_TEMPERATURE, struct.pack("<f", 31.5)))
        return len(data)

    def flush(self):
        pass

    def read(self, size: int):
        data = bytes(self.rx[:size])
        del self.rx[:size]
        return data


def test_device_reuses_one_serial_handle_for_many_operations():
    created = []

    def factory(**kwargs):
        item = FakeSerial(**kwargs)
        created.append(item)
        return item

    device = IPS3608Device(
        "COM_TEST",
        serial_factory=factory,
        min_write_gap=0.0,
        temperature_interval=30.0,
    )
    device.connect()
    first = device.read_status()
    device.set_output(True)
    second = device.read_status()
    device.set_output(False)

    assert len(created) == 1
    assert created[0].open_count == 1
    assert first.voltage_v == second.voltage_v == 5.0
    assert output_packet(True) in created[0].writes
    assert output_packet(False) in created[0].writes

    device.close()
    assert not device.connected


def test_temperature_polling_is_disabled_by_default():
    created = []

    def factory(**kwargs):
        item = FakeSerial(**kwargs)
        created.append(item)
        return item

    device = IPS3608Device("COM_TEST", serial_factory=factory, min_write_gap=0.0)
    device.connect()
    measurement = device.read_status()
    device.close()

    assert measurement.temperature_c is None
    assert temperature_request() not in created[0].writes


def test_windows_error_31_stops_nested_connect_retries():
    calls = 0

    def failed_serial_factory(**kwargs):
        nonlocal calls
        calls += 1
        error = OSError("simulated Windows device failure")
        error.winerror = 31
        raise error

    device = IPS3608Device("COM3", serial_factory=failed_serial_factory)

    with pytest.raises(Exception, match="after 1 attempts"):
        device.connect(attempts=3)

    assert calls == 1
