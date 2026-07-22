# Architecture

## Process model

`ips3608-bridge serve` is the only process that opens the physical serial port. It binds a small newline-delimited JSON service to `127.0.0.1:36080`. Every CLI invocation connects to that local service, performs one allowlisted request, and exits without touching the serial port.

The service owns a persistent serial session but does not run a background measurement monitor by default. Telemetry is refreshed on demand with a 15-second cache, so fast local API polling does not imply fast serial polling. A positive `--poll-interval` explicitly enables the monitor. Automatic temperature polling is disabled because voltage/current/power share one live frame while temperature requires an extra transaction.

## Recovery

If telemetry fails, the service abandons the broken local serial handle, waits before reopening it, and reconnects on the next explicit status/control operation or enabled monitor pass. Every serial frame is paced to protect the Windows USB CDC endpoint. The service never automatically retries an ambiguous output-on command. Output-off may be retried once because repeating it is safe.

The connection/reconnect path is ported from the full automation controller: after opening the PC session it immediately commands output-off and requires voltage telemetry at or below 0.1 V. A connection that cannot prove this safe starting state is rejected.

After a physical connection reaches the verified safe state, ON is held for a three-second stabilization window. Failed Windows USB opens use one- and two-second backoff intervals plus a longer primer delay instead of rapid reopen loops.

An output command is not considered successful merely because the operating system accepted its bytes. `on` must be followed by telemetry above 0.1 V, and `off` must be followed by telemetry at or below 0.1 V.

## Shutdown

`stop` asks the service to shut down. During cleanup it performs, in order:

1. output off;
2. protocol session disconnect;
3. local serial handle close.

The service does not acknowledge or perform shutdown unless output-off is verified by voltage telemetry at or below 0.1 V. If verification fails, the listener remains available for another `off` attempt and the user must treat the physical state as unknown. OFF requests signal priority before waiting for the monitor lock, so a failed background telemetry pass yields before starting reconnect work.

## Safety boundary

The network handler accepts only `health`, `status`, `on`, `off`, and internal `shutdown`. There is no generic command dispatch, raw-byte endpoint, voltage setter, or current setter.
