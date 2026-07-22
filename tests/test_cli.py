import pytest

from ips3608_bridge import cli
from ips3608_bridge.client import BridgeUnavailable
from ips3608_bridge.cli import build_parser


def test_cli_has_no_voltage_current_set_or_raw_command():
    parser = build_parser()
    for command in ("set", "set-voltage", "set-current", "raw", "exec"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_default_poll_interval_is_conservative():
    args = build_parser().parse_args(["start"])
    assert args.poll_interval == 0.0
    assert cli.normalize_poll_interval(args.poll_interval) == 0.0


def test_positive_poll_interval_is_clamped_without_changing_on_demand_zero():
    assert cli.normalize_poll_interval(0.0) == 0.0
    assert cli.normalize_poll_interval(-1.0) == 0.0
    assert cli.normalize_poll_interval(0.1) == 0.25
    assert cli.normalize_poll_interval(15.0) == 15.0


def test_control_command_never_implicitly_starts_service(monkeypatch):
    monkeypatch.setattr(
        cli,
        "request",
        lambda command, **kwargs: {
            "ok": True,
            "service": "running",
            "connected": True,
            "device_port": "SIMULATED",
            "consecutive_errors": 0,
            "reconnect_count": 1,
        },
    )
    monkeypatch.setattr(
        cli,
        "_ensure_started",
        lambda *args, **kwargs: pytest.fail("ordinary commands must not auto-start"),
    )
    assert cli.main(["health"]) == 0


def test_start_refuses_duplicate_when_port_is_occupied(monkeypatch):
    monkeypatch.setattr(
        cli,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(BridgeUnavailable("busy")),
    )
    monkeypatch.setattr(cli, "_port_is_listening", lambda port: True)
    with pytest.raises(BridgeUnavailable, match="refusing to start a duplicate"):
        cli._ensure_started(36080, "COM3", 5.0, False)
