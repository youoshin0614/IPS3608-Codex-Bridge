# Supported protocol subset

The project intentionally implements only a small protocol subset:

| Operation | Command | Register | Payload |
|---|---:|---:|---:|
| Enter PC session | `0xC1` | `0x00` | `0x01` |
| Leave PC session | `0xC1` | `0x00` | `0x00` |
| Read live V/I/P | `0xA1` | `0xC3` | `0x00` |
| Read temperature | `0xA1` | `0xC4` | `0x00` |
| Output off | `0xB1` | `0xDB` | `0x00` |
| Output on | `0xB1` | `0xDB` | `0x01` |

Request frame:

```text
F1 command register payload_length payload... checksum
```

Response frame:

```text
F0 command register payload_length payload... checksum
```

The checksum is the low byte of `register + payload_length + sum(payload)`.

Voltage/current setting registers are intentionally not documented or implemented in this project.

