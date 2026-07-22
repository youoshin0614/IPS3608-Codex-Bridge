# Loaded hardware validation — 2026-07-22

## Setup

- IPS3608 on `COM3`, USB VID:PID `2E3C:5740`.
- Direct motherboard path: `Port_#0004.Hub_#0002`, parent `USB\ROOT_HUB30`.
- External board connected as the load.
- Retained front-panel limits: 5 V / 1 A.
- Bridge telemetry mode: `on_demand`, effective background interval `0.0` seconds.
- Automatic temperature polling disabled.

## Result

- Startup forced output-off and verified 0.000 V before accepting control.
- Output-on was verified by voltage telemetry.
- The loaded run lasted about 199 seconds of service uptime.
- 263 local `status` calls produced only 12 distinct serial telemetry frames because of the 15-second cache.
- Steady telemetry was 5.000 V after startup, 0.243–0.367 A, and 1.214–1.830 W.
- No background telemetry error occurred during the loaded run.
- Output-off completed in about 8.9 seconds and verified 0.000 V. It used one bounded reconnect (`reconnect_count` changed from 1 to 2).
- A second output-off verification, final status, and `stop` all succeeded.
- Final state: 0.000 V, 0.000 A, no listeners on ports 36080/36081, no IPS3608 service process, and Device Manager `CM_PROB_NONE`.

## Important observations

An earlier launcher bug converted the intended on-demand interval `0.0` into a 0.25-second background interval. That caused 60 local API requests to produce 60 physical serial reads and quickly reproduced CDC failure. The launcher now preserves zero, and `health` exposes both `telemetry_mode` and `poll_interval_s` so the effective mode can be verified before output-on.

During this validation, a concurrent `status` request timed out while output-off owned the controller lock for recovery. The safety command itself succeeded and was verified. Clients should treat OFF as the priority operation and avoid issuing concurrent status requests until it returns.

The same device repeatedly produced Windows error 31 and write timeouts when connected through an external `VID_05E3` USB hub at `Port_#0001.Hub_#0003`. Moving it back to the direct motherboard path above was required for this successful run. Software cannot guarantee recovery from a physically wedged USB CDC endpoint; if OFF cannot verify at most 0.1 V, manually disable output.
