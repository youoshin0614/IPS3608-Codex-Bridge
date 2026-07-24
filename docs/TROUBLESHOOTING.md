# Troubleshooting

## The service reports `Write timeout` or no live response

Stop the bridge first:

```powershell
.\ips3608.cmd stop
```

Close vendor software and other serial tools, reconnect the data cable once, then start the bridge. After a successful start, leave the bridge running for the whole debugging topic instead of repeatedly stopping it.

## The front panel is locked

The IPS3608 locks local controls while a PC session is active. This is expected while the persistent bridge is running. Run `ips3608.cmd stop` after the debugging topic to send the protocol disconnect and release the panel.

## `connected=False`

Run:

```powershell
.\ips3608.cmd ports
.\ips3608.cmd health
```

Confirm the selected device port, data cable, power-supply power state, and that no other program owns the port.

## Logs

On Windows, bounded rotating logs are stored under:

```text
%LOCALAPPDATA%\ips3608-codex-bridge\
```

`bridge.log` is the human-readable service log. `errors.jsonl` contains
machine-readable records with a run ID, event, classified error kind, safety
interlock state, and known/unknown output state. Both logs rotate at 1 MB.
Identical errors are emitted once per minute with a `suppressed_repeats` count
instead of flooding the disk.

Inspect diagnostics without opening the serial port:

```powershell
.\ips3608.cmd diagnostics
.\ips3608.cmd --json diagnostics
```

## Safety interlock after Windows error 31/995, short write, or write timeout

These errors latch a safety interlock and mark the physical output state
`unknown`. While latched, the bridge blocks `status` reconnects and all `on`
requests. Change the cable or physical USB port, preferably to a direct
motherboard port, then issue one `off` request. The bridge clears the interlock
only after live voltage telemetry verifies at most 0.1 V.

`health` and `diagnostics` remain available while interlocked. Do not repeatedly
run `status`, restart the service, or reconnect on the same failed USB path.
