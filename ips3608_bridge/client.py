"""Small JSON-over-localhost client for the persistent bridge."""

from __future__ import annotations

import json
import socket
from typing import Any


class BridgeUnavailable(RuntimeError):
    pass


def request(
    command: str,
    host: str = "127.0.0.1",
    tcp_port: int = 36080,
    timeout: float = 6.0,
) -> dict[str, Any]:
    payload = json.dumps({"command": command}, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((host, tcp_port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            chunks = bytearray()
            while len(chunks) <= 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.extend(chunk)
                if b"\n" in chunk:
                    break
    except OSError as exc:
        raise BridgeUnavailable(
            f"bridge is unavailable at {host}:{tcp_port}: {exc}"
        ) from exc

    line = bytes(chunks).split(b"\n", 1)[0]
    if not line:
        raise BridgeUnavailable("bridge returned an empty response")
    try:
        response = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeUnavailable(f"bridge returned invalid JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise BridgeUnavailable("bridge response is not an object")
    return response

