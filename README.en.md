# IPS3608 Codex Bridge

A persistent, localhost-only, switch-safe bridge for the FNIRSI IPS3608 power supply.

The bridge keeps one serial session open and exposes only `health`, `status`, `on`, and `off` to clients. Voltage/current setters and raw protocol passthrough are intentionally absent. Set and verify voltage/current limits manually on the power supply before automation.

See [README.md](README.md) for setup and usage. The source is an independent implementation released under the MIT License.

