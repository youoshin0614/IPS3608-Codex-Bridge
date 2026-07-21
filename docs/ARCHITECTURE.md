# Architecture

## Process model

`ips3608-bridge serve` is the only process that opens the physical serial port. It binds a small newline-delimited JSON service to `127.0.0.1:36080`. Every CLI invocation connects to that local service, performs one allowlisted request, and exits without touching the serial port.

The service keeps a measurement monitor running at a configurable interval, defaulting to five seconds. This mirrors the continuous communication pattern of a desktop control application and avoids repeated USB CDC open/close cycles.

## Recovery

If telemetry fails, the service abandons the broken local serial handle, waits before reopening it, and reconnects on the next monitor pass. Every serial frame is paced to protect the Windows USB CDC endpoint. The service never automatically retries an ambiguous output-on command. Output-off may be retried once because repeating it is safe.

An output command is not considered successful merely because the operating system accepted its bytes. `on` must be followed by telemetry above 0.1 V, and `off` must be followed by telemetry at or below 0.1 V.

## Shutdown

`stop` asks the service to shut down. During cleanup it attempts, in order:

1. output off;
2. protocol session disconnect;
3. local serial handle close.

The cleanup attempts are best-effort because a physically disconnected or failed USB device cannot acknowledge them.

## Safety boundary

The network handler accepts only `health`, `status`, `on`, `off`, and internal `shutdown`. There is no generic command dispatch, raw-byte endpoint, voltage setter, or current setter.
