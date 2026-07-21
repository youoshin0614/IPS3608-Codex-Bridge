# Changelog

## 0.1.1 - 2026-07-21

- Completed no-load hardware validation on an IPS3608 connected as COM3.
- Verified a persistent 53-second session, 15 repeated status requests, and 1.5 V output on/off control with zero reconnects or communication errors.
- Fixed shutdown ordering that could leave a reconnecting monitor process alive and keep COM3 busy.
- Documented telemetry transition delay and switch-only watchdog/authentication limitations.

## 0.1.0 - 2026-07-21

- Initial independent implementation.
- Persistent serial session with localhost command bridge.
- Switch-only API: status, output on, and output off.
- Safe service shutdown and automatic local service startup.
- Simulation mode and automated tests.
