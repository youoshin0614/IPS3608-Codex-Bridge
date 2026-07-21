import pytest

from ips3608_bridge.cli import build_parser


def test_cli_has_no_voltage_current_set_or_raw_command():
    parser = build_parser()
    for command in ("set", "set-voltage", "set-current", "raw", "exec"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])

