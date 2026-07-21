## FNIRSI IPS3608 switch-only power control

Use only this project's `ips3608.cmd` launcher. The service exposes `health`, `status`, `on`, `off`, `start`, `stop`, and `ports`. It cannot change voltage or current and does not allow raw serial commands.

Before using `on`, confirm that the user has manually configured and verified safe voltage/current limits on the IPS3608 front panel. Never attempt to alter these settings through another program.

For hardware tests:

1. Run `ips3608.cmd health` and `ips3608.cmd status`.
2. Use `try/finally` or an equivalent cleanup mechanism.
3. Run `ips3608.cmd on`, then perform the test.
4. Always run `ips3608.cmd off` in cleanup, including after failures, timeouts, or interruptions.
5. Keep the service running throughout one debugging topic so commands reuse the persistent connection.
6. Run `ips3608.cmd stop` after the debugging topic is complete; stopping the service attempts output-off before releasing the serial port.

Treat `on`, `off`, and `stop` as real hardware side effects. Report status readings and whether the final output-off succeeded. If current is unexpectedly high, immediately turn the output off and stop testing.

