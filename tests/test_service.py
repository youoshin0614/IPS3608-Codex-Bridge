import threading

from ips3608_bridge.client import request
from ips3608_bridge.device import SimulatedDevice
from ips3608_bridge.service import BridgeController, LocalBridgeServer


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

