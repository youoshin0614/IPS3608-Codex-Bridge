# Hardware recovery validation — 2026-07-24

## Incident

- The IPS3608 enumerated as `COM3` with Windows problem code 0 on the known
  direct motherboard path `Port_#0004.Hub_#0002`.
- The first service run failed its mandatory safe-start transaction with a
  serial write timeout.
- The bridge latched `safety_interlock=true`, marked the physical output
  `unknown`, blocked ordinary reconnects and output-on, and retained only the
  bounded output-off recovery path.
- One explicit output-off request also timed out. No further serial operation
  was attempted while the output state was unknown.

## Physical recovery

The output was manually disabled. USB was disconnected, allowed to reset, and
reconnected on the direct motherboard path. The interlocked service process was
then terminated without sending another serial command, ensuring that the
updated OFF-only recovery path would be loaded.

## Verified result

- New service process started at `2026-07-24 01:18:14` local time.
- Initial connection forced output-off and verified live telemetry at
  `0.000 V`, `0.000 A`, and `0.000 W`.
- Health reported `connected=true`, `reconnect_count=1`,
  `consecutive_errors=0`, `output_state=off`, and
  `safety_interlock=false`.
- A second status request after the 15-second cache horizon performed a new
  physical telemetry transaction and again measured `0.000 V`, `0.000 A`, and
  `0.000 W`.
- The new run produced no structured error record. Records remaining in
  `errors.jsonl` belong to the earlier failed run ID
  `385a0f465b554a0b9f347def0b134130`.
- Output-on was intentionally not tested because this recovery validation did
  not include renewed confirmation of the front-panel voltage/current limits
  and load envelope.

## Final state at the end of recovery validation

The bridge was later stopped before protocol-order investigation. The IPS3608
output was verified off at 0 V before process exit.

## Reconnection validation later the same day

- Reconnecting through external hub parent `VID_05E3&PID_0608` reproduced a
  stale-handle/Windows 995 failure. No output-on command was issued.
- The service was stopped before the next physical reset. Moving the device to
  the direct motherboard path `Port_#0004.Hub_#0002`, parent
  `USB\ROOT_HUB30`, restored communication immediately.
- Safe start verified output-off at 0.000 V.
- A fresh physical status read after the 15-second cache horizon again returned
  0.000 V, 0.000 A, and 0.000 W with zero connection errors.
- An explicit output-off command succeeded and independently verified 0.000 V.
- Final health: connected, one successful connection, zero consecutive errors,
  safety interlock clear, output state off, and on-demand telemetry enabled.

## Remote-output RCA later the same day

Manual RUN produced approximately 5.00 V, proving the power stage was healthy.
Static analysis of FNIRSI's official desktop application showed that its ON
frame matches this project, but its activation transaction is ordered
`ON -> voltage -> current`. The automation service previously used
`current -> voltage -> ON`.

After matching the official order, a 5.00 V / 1.00 A no-load hardware test
verified remote output at 5.000 V. Emergency-off and shutdown both subsequently
verified 0.000 V. Both bridge and automation services were stopped afterward.
The full evidence is recorded in the automation repository at
`docs/HARDWARE-RCA-2026-07-24.md`.
