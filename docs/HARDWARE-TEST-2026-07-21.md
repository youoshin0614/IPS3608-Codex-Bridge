# Switch-only Bridge hardware validation

Date: 2026-07-21  
Device: FNIRSI IPS3608 on `COM3`  
USB identity: `USB\VID_2E3C&PID_5740` (unique device serial omitted)  
Load: none

## Results

- Dependency and Python compile checks passed.
- Automated tests: 8/8 passed.
- Source boundary scan found no voltage/current setter, setter register, raw command endpoint, or public network bind.
- `set` was rejected as an unavailable command with exit code 2.
- Persistent hardware connection stayed at `reconnect_count=1` with zero errors.
- Fifteen repeated status requests over approximately 15 seconds succeeded without disconnecting.
- Output-on produced 1.5 V and 0 A using a low-risk setpoint previously applied by the authorized automation edition.
- Output-off returned telemetry to 0 V.
- Safe service stop released TCP port 36080, the Python process, and COM3.
- Device Manager reported `CM_PROB_NONE` after shutdown.

## Issue corrected during validation

The original shutdown path could leave the service alive if its monitor was reconnecting. That process continued to occupy COM3 and caused `Access denied` or `Write timeout` in later clients.

Shutdown now stops monitoring and completes best-effort output-off/device release before acknowledging success. Repeated tests confirmed that no listener or service process remains after `stop`.

## Mandatory usage warnings

1. This edition cannot read, set, or enforce voltage/current limits. Verify both values manually on the IPS3608 front panel before allowing `on`.
2. There is no output-idle watchdog. If Codex, the shell, or the controlling process crashes after `on`, output may remain enabled. Always use `try/finally` and call `off` during cleanup.
3. There is no capability token. Any local process able to reach TCP port 36080 can request `on` or `off`. This is a low-trust convenience API, not an adversarial security boundary.
4. IPS3608 telemetry can lag an output transition. The first immediate reading after `on` may still show 0 V, and the first immediate reading after `off` may show the prior voltage. Wait about one second before judging the result.
5. The front panel is expected to remain locked while the persistent PC session is active. Run `stop` to release it.
6. Do not run this service and the full automation service against the same COM port at the same time.
7. This was a no-load test. Current limiting under load, OCP/OVP, thermal behavior, and cable-disconnect recovery were not verified.

## Required automation pattern

```powershell
$psu = "C:\path\to\IPS3608-Codex-Bridge\ips3608.cmd"

try {
    & $psu on
    if ($LASTEXITCODE -ne 0) { throw "power-on failed" }
    Start-Sleep -Seconds 1
    & $psu status
    # Hardware test
}
finally {
    & $psu off
    Start-Sleep -Seconds 1
    & $psu status
}
```
