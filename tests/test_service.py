import threading

from ips3608_bridge.client import request
from ips3608_bridge.device import SimulatedDevice
from ips3608_bridge.service import BridgeController, LocalBridgeServer


class IgnoredOutputOnDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.on_write_count = 0

    def set_output(self, enabled: bool) -> None:
        if enabled:
            self.on_write_count += 1
            self.output_enabled = False
            return
        super().set_output(False)


class AmbiguousOnWriteFailureDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.on_write_count = 0
        self.off_write_count = 0

    def set_output(self, enabled: bool) -> None:
        if enabled:
            self.on_write_count += 1
            self.output_enabled = True
            raise RuntimeError("write completion was ambiguous")
        self.off_write_count += 1
        super().set_output(False)


class PersistentOffFailureDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.fail_off = False

    def set_output(self, enabled: bool) -> None:
        if not enabled and self.fail_off:
            raise RuntimeError("persistent output-off write failure")
        super().set_output(enabled)


class OneShotOffFailureDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.fail_next_off = False

    def set_output(self, enabled: bool) -> None:
        if not enabled and self.fail_next_off:
            self.fail_next_off = False
            raise RuntimeError("short serial write: wrote 0 of 6 bytes")
        super().set_output(enabled)


class CountingStatusDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.read_count = 0

    def read_status(self):
        self.read_count += 1
        return super().read_status()


class Windows31ThenRecoverDevice(SimulatedDevice):
    def __init__(self):
        super().__init__()
        self.fail_connect = True
        self.connect_attempts = 0

    def connect(self, attempts: int = 3) -> None:
        self.connect_attempts += 1
        if self.fail_connect:
            error = OSError("simulated Windows device failure")
            error.winerror = 31
            raise error
        super().connect(attempts=attempts)


def test_controller_keeps_one_device_connection_and_blocks_unsafe_commands():
    device = SimulatedDevice()
    controller = BridgeController(device, poll_interval=60.0)
    controller.start()

    assert controller.handle("status")["ok"] is True
    assert controller.handle("on")["ok"] is True
    assert controller.handle("status")["ok"] is True
    assert controller.handle("off")["ok"] is True
    assert device.connect_count == 1

    for command in ("set", "set_voltage", "set_current", "raw", "exec"):
        response = controller.handle(command)
        assert response["ok"] is False
        assert response["error"] == "command_not_allowed"

    controller.close()
    assert device.output_enabled is False


def test_local_json_service_reuses_the_persistent_controller():
    device = SimulatedDevice()
    controller = BridgeController(device, poll_interval=60.0)
    server = LocalBridgeServer(("127.0.0.1", 0), controller)
    controller.set_shutdown_callback(server.shutdown)
    controller.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tcp_port = server.server_address[1]

    try:
        assert request("health", tcp_port=tcp_port)["ok"] is True
        assert request("status", tcp_port=tcp_port)["ok"] is True
        assert request("on", tcp_port=tcp_port)["output"] == "on"
        assert request("off", tcp_port=tcp_port)["output"] == "off"
        denied = request("set_voltage", tcp_port=tcp_port)
        assert denied["error"] == "command_not_allowed"
        assert device.connect_count == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        controller.close()


def test_on_requires_nonzero_voltage_and_is_never_retried():
    device = IgnoredOutputOnDevice()
    controller = BridgeController(
        device,
        poll_interval=60.0,
        output_verify_timeout=0.05,
    )
    controller.start()
    try:
        response = controller.handle("on")
        assert response["ok"] is False
        assert response["error"] == "output_verification_failed"
        assert device.on_write_count == 1
        assert device.output_enabled is False
        health = controller.handle("health")
        assert health["last_error_kind"] == "device_error"
        assert health["consecutive_errors"] == 1
        assert health["output_state"] == "off"
    finally:
        controller.close()


def test_ambiguous_on_write_is_not_retried_and_safe_off_is_verified():
    device = AmbiguousOnWriteFailureDevice()
    controller = BridgeController(
        device,
        poll_interval=60.0,
        output_verify_timeout=0.05,
    )
    controller.start()
    try:
        response = controller.handle("on")
        assert response["ok"] is False
        assert response["error"] == "output_command_failed"
        assert device.on_write_count == 1
        assert device.off_write_count >= 1
        assert device.output_enabled is False
        assert controller.state.output_commanded is False
    finally:
        controller.close()


def test_shutdown_is_refused_until_output_off_is_verified():
    device = PersistentOffFailureDevice()
    controller = BridgeController(
        device,
        poll_interval=60.0,
        output_verify_timeout=0.05,
    )
    callback_called = False

    def callback():
        nonlocal callback_called
        callback_called = True

    controller.set_shutdown_callback(callback)
    controller.start()
    try:
        assert controller.handle("on")["ok"]
        device.fail_off = True

        response = controller.handle("shutdown")

        assert response["ok"] is False
        assert response["error"] == "output_off_unverified"
        assert controller.state.output_commanded is None
        assert controller._stop_event.is_set() is False
        assert callback_called is False
    finally:
        device.fail_off = False
        controller.handle("off")
        controller.close()


def test_failed_explicit_off_marks_output_unknown():
    device = PersistentOffFailureDevice()
    controller = BridgeController(
        device,
        poll_interval=60.0,
        output_verify_timeout=0.05,
    )
    controller.start()
    try:
        assert controller.handle("on")["ok"]
        device.fail_off = True

        response = controller.handle("off")

        assert response["ok"] is False
        assert response["error"] == "output_off_unverified"
        health = controller.handle("health")
        assert health["output_state"] == "unknown"
        assert health["last_error_kind"] == "device_error"
        assert health["safety_interlock"] is True
    finally:
        device.fail_off = False
        controller.handle("off")
        controller.close()


def test_off_reconnect_uses_automation_safe_start_contract():
    device = OneShotOffFailureDevice()
    controller = BridgeController(device, poll_interval=60.0)
    controller.start()
    try:
        assert controller.handle("on")["ok"]
        device.fail_next_off = True

        response = controller.handle("off")

        assert response["ok"] is True
        assert response["verified_voltage_v"] <= 0.1
        assert device.output_enabled is False
        assert device.connect_count == 2
        assert controller.state.output_commanded is False
    finally:
        controller.close()


def test_default_on_demand_mode_does_not_poll_serial_in_background():
    device = CountingStatusDevice()
    controller = BridgeController(device)
    controller.start()
    try:
        reads_after_start = device.read_count
        assert controller._monitor is None
        health = controller.handle("health")
        assert health["telemetry_mode"] == "on_demand"
        assert health["poll_interval_s"] == 0.0

        for _ in range(20):
            assert controller.handle("status")["ok"]

        assert device.read_count == reads_after_start
    finally:
        controller.close()


def test_windows_error_31_latches_interlock_until_verified_off():
    device = Windows31ThenRecoverDevice()
    controller = BridgeController(
        device,
        poll_interval=0.0,
        output_verify_timeout=0.05,
    )
    controller.start()
    try:
        attempts_after_fault = device.connect_attempts
        health = controller.handle("health")
        assert health["safety_interlock"] is True
        assert health["last_error_kind"] == "windows_error_31"
        assert health["output_state"] == "unknown"

        assert controller.handle("status")["error"] == "safety_interlock_active"
        assert controller.handle("on")["error"] == "safety_interlock_active"
        assert device.connect_attempts == attempts_after_fault

        device.fail_connect = False
        response = controller.handle("off")
        assert response["ok"] is True
        assert response["verified_voltage_v"] <= 0.1
        assert controller.handle("health")["safety_interlock"] is False
        assert controller.handle("health")["output_state"] == "off"
    finally:
        controller.close()
