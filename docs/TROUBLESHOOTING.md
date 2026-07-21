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

On Windows, service logs are stored under:

```text
%LOCALAPPDATA%\ips3608-codex-bridge\
```

