# Security policy

## Scope

The localhost service accepts a fixed command allowlist and contains no voltage/current setter or raw serial passthrough. It binds to `127.0.0.1` by default.

This is an API-level safety boundary. It cannot prevent another local process with permission to open the serial device from bypassing the bridge.

## Reporting

Please report cases where a network request can execute a non-allowlisted command, alter voltage/current setpoints, bind the service publicly without explicit configuration, or bypass safe shutdown behavior.

Do not include destructive proof-of-concept payloads against real connected hardware. Reproduce with simulation or a fake serial backend whenever possible.

