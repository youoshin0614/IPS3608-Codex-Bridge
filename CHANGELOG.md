# Changelog

## 0.3.0 - 2026-07-22

- Switch to on-demand telemetry with a 15-second cache and disable optional temperature polling by default.
- Give output-off requests priority over background recovery work.
- Refuse `stop` and keep the service available when voltage telemetry cannot verify output-off.
- Allow safety commands enough client time to finish bounded reconnect and verification work without duplicate retries.
- Port the full automation edition's force-safe-start and reconnect-off verification contract while keeping all setpoint and raw-command interfaces absent.
- Enforce a three-second physical-device stabilization window before ON and lengthen Windows USB recovery backoff.
- Fix the background launcher so a zero on-demand interval remains zero instead of being silently clamped to 0.25 seconds; expose the effective telemetry mode in health responses.

## 0.2.0 - 2026-07-21

- Require explicit `start`; ordinary commands no longer auto-start a service.
- Refuse duplicate startup when the localhost port is occupied or unresponsive.
- Increase the default polling interval from one to five seconds.
- Pace serial writes, lengthen write timeout, cool down before reconnect, and reduce temperature polling.
- Verify `on` and `off` against real voltage telemetry without retrying ambiguous `on` commands.
- Wait for the listener to remain closed before reporting a successful stop.
- Avoid blocking 64-byte reads that can aggravate the IPS3608 Windows CDC driver, and use a guarded recovery-open sequence for intermittent error 995.
- Document the physical USB-path fault found during validation and the requirement for manual shutdown when software cannot verify output-off.

## 0.1.1 - 2026-07-21

- Completed no-load hardware validation on an IPS3608 connected as COM3.
- Verified a persistent 53-second session, 15 repeated status requests, and 1.5 V output on/off control with zero reconnects or communication errors.
- Fixed shutdown ordering that could leave a reconnecting monitor process alive and keep COM3 busy.
- Documented telemetry transition delay and switch-only watchdog/authentication limitations.

## 0.1.0 - 2026-07-21

- Initial public release.
- Persistent serial session with localhost command bridge.
- Switch-only API: status, output on, and output off.
- Safe service shutdown and automatic local service startup.
- Simulation mode and automated tests.
