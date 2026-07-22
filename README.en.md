# IPS3608 Codex Bridge

A persistent, localhost-only, switch-safe bridge for the FNIRSI IPS3608 power supply.

The bridge keeps one serial session open and exposes only `health`, `status`, `on`, and `off` to clients. Voltage/current setters and raw protocol passthrough are intentionally absent. Set and verify voltage/current limits manually on the power supply before automation.

See [README.md](README.md) for setup and usage. The project is released under the MIT License.

Stop the bridge and change the data cable or physical USB port after short writes, Windows error 995, or error 31. If `off` cannot verify 0 V, treat output as unknown and shut down the power supply manually.

Telemetry is on-demand by default, with no background serial polling, and automatic temperature polling is disabled. Repeated client `status` calls return a 15-second cache rather than repeatedly touching the CDC endpoint. Physical connections also observe a three-second stabilization window before ON. `stop` refuses to terminate the service unless output-off is verified at or below 0.1 V.

Do not issue concurrent status requests while OFF is running; OFF owns the serial path until recovery and verification finish. See [`docs/HARDWARE-TEST-2026-07-22.md`](docs/HARDWARE-TEST-2026-07-22.md) for the loaded validation.

The bridge uses the full automation edition's fail-safe connection core: every initial connection and reconnect must command OFF and verify at most 0.1 V before use. Setpoint registers, device methods, network commands, and CLI commands remain absent from this switch-only build.
