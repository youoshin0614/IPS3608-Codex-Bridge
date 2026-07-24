"""Structured diagnostics, error classification, and bounded log files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading
import time
from typing import Any
from uuid import uuid4


LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
ERROR_LOG_BACKUP_COUNT = 5
ERROR_REPEAT_WINDOW_S = 60.0


@dataclass(frozen=True)
class ErrorDetails:
    kind: str
    requires_manual_recovery: bool
    action: str


_ERROR_RULES: tuple[tuple[str, re.Pattern[str], bool, str], ...] = (
    (
        "windows_error_31",
        re.compile(r"(?:win(?:dows)?error|error)[^\d]{0,4}31\b|winerror\s*31", re.I),
        True,
        "Stop automatic I/O. Change the USB cable or physical USB port, then use OFF.",
    ),
    (
        "windows_error_995",
        re.compile(
            r"(?:win(?:dows)?error|error)[^\d]{0,4}995\b|"
            r"winerror\s*995|none\s*,\s*995\)",
            re.I,
        ),
        True,
        "Stop automatic I/O. Change the USB cable or physical USB port, then use OFF.",
    ),
    (
        "stale_serial_handle",
        re.compile(
            r"permissionerror\(13,.+none\s*,\s*22\)|"
            r"oserror\(22,.+(?:i/o|io|command|线程|命令)",
            re.I,
        ),
        True,
        "The serial handle is stale. Stop I/O, reset the USB path, then use OFF.",
    ),
    (
        "short_serial_write",
        re.compile(r"short serial write|wrote \d+ of \d+ bytes", re.I),
        True,
        "Stop automatic I/O. Change the USB path, then use OFF.",
    ),
    (
        "serial_write_timeout",
        re.compile(r"write timeout", re.I),
        True,
        "Stop automatic I/O. Change the USB path, then use OFF.",
    ),
    (
        "device_missing",
        re.compile(r"filenotfounderror|cannot find the file|找不到指定的文件", re.I),
        False,
        "Connect the IPS3608 to the configured serial port.",
    ),
    (
        "device_busy",
        re.compile(r"permissionerror|access is denied|拒绝访问", re.I),
        False,
        "Close other serial software and retry without starting a duplicate bridge.",
    ),
    (
        "serial_response_timeout",
        re.compile(r"timeout waiting for register", re.I),
        False,
        "Keep output state unknown; use OFF if the failure repeats.",
    ),
)


def _exception_chain_text(exc: BaseException | str) -> str:
    if isinstance(exc, str):
        return exc
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        winerror = getattr(current, "winerror", None)
        if winerror is not None:
            parts.append(f"WinError {winerror}")
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def classify_error(exc: BaseException | str) -> ErrorDetails:
    """Classify wrapped serial exceptions without depending on localized text alone."""
    text = _exception_chain_text(exc)
    for kind, pattern, manual, action in _ERROR_RULES:
        if pattern.search(text):
            return ErrorDetails(kind, manual, action)
    return ErrorDetails(
        "device_error",
        False,
        "Inspect the structured error record and keep output state conservative.",
    )


class JsonLineFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "run_id": self.run_id,
        }
        for field in (
            "error_kind",
            "exception_type",
            "safety_interlock",
            "output_state",
            "suppressed_repeats",
            "device_port",
            "command",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(state_dir: Path) -> str:
    """Configure process logging with bounded human and JSONL files."""
    state_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    text_handler = RotatingFileHandler(
        state_dir / "bridge.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    text_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    error_handler = RotatingFileHandler(
        state_dir / "errors.jsonl",
        maxBytes=LOG_MAX_BYTES,
        backupCount=ERROR_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(JsonLineFormatter(run_id))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(text_handler)
    root.addHandler(error_handler)
    return run_id


class ErrorReporter:
    """Suppress identical error floods while preserving periodic counts."""

    def __init__(self, repeat_window_s: float = ERROR_REPEAT_WINDOW_S) -> None:
        self.repeat_window_s = max(0.0, repeat_window_s)
        self._entries: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def report(
        self,
        logger: logging.Logger,
        event: str,
        exc: BaseException | str,
        *,
        output_state: str,
        safety_interlock: bool,
        device_port: str,
        now: float | None = None,
    ) -> ErrorDetails:
        details = classify_error(exc)
        message = str(exc)
        signature = f"{event}|{details.kind}|{message}"
        current = time.monotonic() if now is None else now
        with self._lock:
            previous = self._entries.get(signature)
            if previous is not None and current - previous[0] < self.repeat_window_s:
                self._entries[signature] = (previous[0], previous[1] + 1)
                return details
            suppressed = 0 if previous is None else previous[1]
            self._entries[signature] = (current, 0)
        logger.warning(
            "%s: %s",
            event.replace("_", " "),
            message,
            extra={
                "event": event,
                "error_kind": details.kind,
                "exception_type": (
                    type(exc).__name__ if isinstance(exc, BaseException) else "str"
                ),
                "safety_interlock": safety_interlock,
                "output_state": output_state,
                "suppressed_repeats": suppressed,
                "device_port": device_port,
            },
        )
        return details


def diagnostics_snapshot(state_dir: Path, recent_limit: int = 20) -> dict[str, Any]:
    """Read local diagnostics without contacting the service or serial device."""
    files = []
    if state_dir.exists():
        for path in sorted(state_dir.glob("*.log*")) + sorted(
            state_dir.glob("*.jsonl*")
        ):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                }
            )

    recent: list[dict[str, Any]] = []
    error_path = state_dir / "errors.jsonl"
    if error_path.exists():
        lines = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-max(0, recent_limit) :]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = {"event": "malformed_error_record", "raw": line}
            recent.append(item)
    return {
        "ok": True,
        "state_directory": str(state_dir),
        "files": files,
        "recent_errors": recent,
        "error_kinds": sorted(
            {
                str(item.get("error_kind"))
                for item in recent
                if item.get("error_kind")
            }
        ),
    }


def error_details_dict(details: ErrorDetails) -> dict[str, Any]:
    return asdict(details)
