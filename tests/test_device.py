import struct

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

    device = IPS3608Device("COM_TEST", serial_factory=factory)
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

