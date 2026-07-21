"""Command-line interface for the persistent localhost bridge."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable

from serial.tools import list_ports

from .client import BridgeUnavailable, request
from .device import IPS3608Device, SimulatedDevice
from .service import run_service


DEFAULT_TCP_PORT = 36080
DEFAULT_DEVICE_PORT = "COM3"


def state_directory() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path.home() / ".local" / "state"
    path = root / "ips3608-codex-bridge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ips3608-bridge",
        description="Persistent switch-only bridge for FNIRSI IPS3608",
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=int(os.environ.get("IPS3608_BRIDGE_PORT", DEFAULT_TCP_PORT)),
        help=f"localhost bridge port (default: {DEFAULT_TCP_PORT})",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")

    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start the persistent bridge")
    start.add_argument(
        "--device-port",
        default=os.environ.get("IPS3608_PORT", DEFAULT_DEVICE_PORT),
    )
    start.add_argument("--poll-interval", type=float, default=1.0)
    start.add_argument("--simulate", action="store_true")

    serve = commands.add_parser("serve", help=argparse.SUPPRESS)
    serve.add_argument(
        "--device-port",
        default=os.environ.get("IPS3608_PORT", DEFAULT_DEVICE_PORT),
    )
    serve.add_argument("--poll-interval", type=float, default=1.0)
    serve.add_argument("--simulate", action="store_true")

    for name, help_text in (
        ("health", "show service and connection health"),
        ("status", "show latest read-only measurement"),
        ("on", "enable power output"),
        ("off", "disable power output"),
        ("stop", "safely stop the bridge and release the device"),
        ("ports", "list available serial ports"),
    ):
        commands.add_parser(name, help=help_text)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if args.command == "serve":
        return _serve(args)
    if args.command == "ports":
        return _ports(args.json)
    if args.command == "start":
        response = _ensure_started(
            args.tcp_port,
            device_port=args.device_port,
            poll_interval=args.poll_interval,
            simulate=args.simulate,
        )
        return _print_response("health", response, args.json)
    if args.command == "stop":
        return _stop(args.tcp_port, args.json)

    try:
        _ensure_started(
            args.tcp_port,
            device_port=os.environ.get("IPS3608_PORT", DEFAULT_DEVICE_PORT),
            poll_interval=1.0,
            simulate=os.environ.get("IPS3608_SIMULATE") == "1",
        )
        response = request(args.command, tcp_port=args.tcp_port)
    except BridgeUnavailable as exc:
        return _print_error(str(exc), args.json)
    return _print_response(args.command, response, args.json)


def _serve(args: argparse.Namespace) -> int:
    log_path = state_directory() / "bridge.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )
    device: Any
    if args.simulate:
        device = SimulatedDevice()
    else:
        device = IPS3608Device(args.device_port)
    try:
        run_service(device, tcp_port=args.tcp_port, poll_interval=args.poll_interval)
        return 0
    except OSError as exc:
        logging.exception("bridge service failed")
        return _print_error(f"bridge service failed: {exc}", args.json)


def _ensure_started(
    tcp_port: int,
    device_port: str,
    poll_interval: float,
    simulate: bool,
) -> dict[str, Any]:
    try:
        return request("health", tcp_port=tcp_port, timeout=0.5)
    except BridgeUnavailable:
        pass

    command = [
        sys.executable,
        "-m",
        "ips3608_bridge",
        "--tcp-port",
        str(tcp_port),
        "serve",
        "--device-port",
        device_port,
        "--poll-interval",
        str(max(0.25, poll_interval)),
    ]
    if simulate:
        command.append("--simulate")

    log_path = state_directory() / "launcher.log"
    log_stream = log_path.open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).resolve().parent.parent,
            close_fds=True,
            creationflags=creationflags,
        )
    finally:
        log_stream.close()

    deadline = time.monotonic() + 10.0
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            return request("health", tcp_port=tcp_port, timeout=0.5)
        except BridgeUnavailable as exc:
            last_error = exc
            time.sleep(0.15)
    raise BridgeUnavailable(f"bridge did not start within 10 seconds: {last_error}")


def _stop(tcp_port: int, as_json: bool) -> int:
    try:
        response = request("shutdown", tcp_port=tcp_port)
    except BridgeUnavailable as exc:
        return _print_error(str(exc), as_json)
    code = _print_response("stop", response, as_json)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            request("health", tcp_port=tcp_port, timeout=0.2)
        except BridgeUnavailable:
            return code
        time.sleep(0.1)
    return _print_error("bridge acknowledged shutdown but is still running", as_json)


def _ports(as_json: bool) -> int:
    ports = [
        {
            "device": item.device,
            "description": item.description,
            "hwid": item.hwid,
        }
        for item in list_ports.comports()
    ]
    if as_json:
        print(json.dumps({"ok": True, "ports": ports}, ensure_ascii=False))
    elif not ports:
        print("No serial ports found")
    else:
        for item in ports:
            print(f"{item['device']}: {item['description']} [{item['hwid']}]")
    return 0


def _print_response(command: str, response: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(response, ensure_ascii=False, sort_keys=True))
        return 0 if response.get("ok") else 1

    if not response.get("ok"):
        print(f"Error: {response.get('message') or response.get('error')}", file=sys.stderr)
        return 1

    if command == "status":
        measurement = response["measurement"]
        temperature = measurement.get("temperature_c")
        temp_text = "n/a" if temperature is None else f"{temperature:.2f} C"
        print(
            f"V={measurement['voltage_v']:.3f}V  "
            f"I={measurement['current_a']:.3f}A  "
            f"P={measurement['power_w']:.3f}W  "
            f"T={temp_text}  age={response['measurement_age_s']:.2f}s"
        )
    elif command == "health" or command == "start":
        print(
            f"service={response.get('service')} "
            f"connected={response.get('connected')} "
            f"port={response.get('device_port')} "
            f"errors={response.get('consecutive_errors')} "
            f"reconnects={response.get('reconnect_count')}"
        )
        if response.get("last_error"):
            print(f"last_error={response['last_error']}")
    elif command in {"on", "off"}:
        print(f"Output {response['output']}")
    else:
        print(response.get("message", "OK"))
    return 0


def _print_error(message: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 1

