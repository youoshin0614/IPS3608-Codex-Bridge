# Contributing

Contributions are welcome, especially reproducible reports for different IPS3608 firmware and Windows USB CDC behavior.

## Development setup

```powershell
.\install.ps1
.\.venv\Scripts\python.exe -m pytest
```

Use simulation or a fake serial backend for automated tests. Tests must not energize real hardware.

## Safety requirements

- Do not add voltage/current setters or a raw-byte passthrough to the public service.
- Keep the network listener restricted to localhost.
- Never automatically retry an ambiguous output-on command.
- Service shutdown must continue to make a best-effort output-off attempt.
- Any hardware integration test must document its manually configured voltage/current limits and must finish with output off.

## Pull requests

Keep changes focused, add tests, update relevant documentation, and explain hardware/firmware versions when behavior is device-specific.

