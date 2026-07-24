import json
import logging

import ips3608_bridge.diagnostics as diagnostics_module
from ips3608_bridge.diagnostics import (
    ErrorReporter,
    JsonLineFormatter,
    classify_error,
    configure_logging,
    diagnostics_snapshot,
)


def windows_error(code: int) -> OSError:
    error = OSError(f"simulated Windows device failure {code}")
    error.winerror = code
    return error


def test_wrapped_windows_error_31_requires_manual_recovery():
    try:
        raise windows_error(31)
    except OSError as cause:
        wrapped = RuntimeError("serial open failed")
        wrapped.__cause__ = cause

    details = classify_error(wrapped)

    assert details.kind == "windows_error_31"
    assert details.requires_manual_recovery is True
    assert "USB" in details.action


def test_pyserial_argument_only_windows_995_is_classified():
    details = classify_error(
        "Cannot configure port: OSError(22, 'operation aborted', None, 995)"
    )

    assert details.kind == "windows_error_995"
    assert details.requires_manual_recovery is True


def test_stale_permission_error_handle_is_classified():
    details = classify_error(
        "WriteFile failed (PermissionError(13, 'device command failed', None, 22))"
    )

    assert details.kind == "stale_serial_handle"
    assert details.requires_manual_recovery is True


def test_error_reporter_suppresses_repeats_and_reports_count(caplog):
    reporter = ErrorReporter(repeat_window_s=60.0)
    logger = logging.getLogger("test.error.reporter")

    with caplog.at_level(logging.WARNING):
        for now in (10.0, 20.0, 71.0):
            reporter.report(
                logger,
                "status_refresh_failed",
                "COM3 missing",
                output_state="unknown",
                safety_interlock=False,
                device_port="COM3",
                now=now,
            )

    matching = [
        record for record in caplog.records if record.name == "test.error.reporter"
    ]
    assert len(matching) == 2
    assert matching[-1].suppressed_repeats == 1


def test_json_formatter_and_offline_snapshot(tmp_path):
    record = logging.LogRecord(
        "ips3608.test",
        logging.WARNING,
        __file__,
        1,
        "transport failed",
        (),
        None,
    )
    record.event = "status_refresh_failed"
    record.error_kind = "windows_error_31"
    record.output_state = "unknown"
    line = JsonLineFormatter("run-123").format(record)
    (tmp_path / "errors.jsonl").write_text(line + "\n", encoding="utf-8")

    payload = json.loads(line)
    snapshot = diagnostics_snapshot(tmp_path)

    assert payload["run_id"] == "run-123"
    assert payload["error_kind"] == "windows_error_31"
    assert snapshot["recent_errors"][0]["output_state"] == "unknown"
    assert snapshot["error_kinds"] == ["windows_error_31"]


def test_configured_logs_rotate_and_keep_valid_jsonl(tmp_path, monkeypatch):
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    monkeypatch.setattr(diagnostics_module, "LOG_MAX_BYTES", 700)
    configured_handlers = []
    try:
        configure_logging(tmp_path)
        configured_handlers = list(root.handlers)
        logger = logging.getLogger("ips3608.rotation-test")
        for index in range(20):
            logger.warning(
                "simulated fault %s %s",
                index,
                "x" * 100,
                extra={
                    "event": "rotation_test",
                    "error_kind": "device_error",
                    "output_state": "unknown",
                },
            )
        for handler in configured_handlers:
            handler.flush()

        assert (tmp_path / "bridge.log.1").exists()
        assert (tmp_path / "errors.jsonl.1").exists()
        for path in tmp_path.glob("errors.jsonl*"):
            for line in path.read_text(encoding="utf-8").splitlines():
                assert json.loads(line)["event"] == "rotation_test"
    finally:
        for handler in configured_handlers:
            root.removeHandler(handler)
            handler.close()
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
