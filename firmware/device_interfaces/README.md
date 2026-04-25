# LABKickstart device convention

Every BLE-connected sensor module in this project advertises the same way and
emits events with the same shape. That's what lets the Pi treat them
uniformly: one BLE client, one parser, and the kit/Sample model on the server
side never has to know what hardware produced an event.

If you're writing a new module, follow this spec.

## Device name

`LK-<ModuleType>-<id>`

| Example            | Meaning                              |
|--------------------|--------------------------------------|
| `LK-Photogate-A`   | First photogate module (gate A)      |
| `LK-Photogate-B`   | Second photogate module (gate B)     |
| `LK-IMU-01`        | First IMU module                     |
| `LK-LoadCell-01`   | First load-cell module               |

The Pi-side scanner uses the `LK-` prefix to find LABKickstart modules and
ignore everything else on the air.

## BLE service & characteristic

One service, one events characteristic. Same UUIDs on every module.

```
Service UUID         5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f
Events char UUID     5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f
                     properties: NOTIFY (required) + READ (optional)
                     descriptor: BLE2902 (CCCD) so the Pi can subscribe
```

Do not invent new UUIDs per module. If you need to publish multiple values,
emit multiple events on the same characteristic.

## Event payload

Each BLE notification is one UTF-8 JSON object on its own.

Required fields:

| Field     | Type   | Notes                                                        |
|-----------|--------|--------------------------------------------------------------|
| `channel` | string | snake_case identifier, units in the name (`break_us`, `pitch_deg`, `force_n`) |
| `value`   | number | the measurement                                              |

Optional extras: any other fields the module wants to attach (sequence
numbers, raw counters, calibration flags, etc.). The Pi-side parser maps
`channel` and `value` directly onto a `Sample`; extras are preserved in the
event stream but ignored by the kits unless they explicitly look for them.

```json
{"channel":"gate_A_break_us","value":59917}
{"channel":"pitch_deg","value":59.05}
{"channel":"force_n","value":12.4,"raw_counts":83214}
```

Channel names are stable, lowercase, snake_case, and self-describing. They
should include units (e.g. `_us`, `_n`, `_deg`, `_mps`). The kits and CSVs
on the Pi key off these names.

## Cadence

- **Event-driven sensors** (photogate, button, switch): emit one notification
  per real event. Don't synthesize a continuous stream.
- **Continuous sensors** (IMU, load cell, thermistor): emit at a fixed rate.
  Cap at **100 Hz per channel** unless you have a specific reason to go
  higher. The BLE GATT layer can keep up, but slow centrals (laptops,
  phones) start dropping packets above that.

## Connection lifecycle

- Implement `BLEServerCallbacks::onDisconnect` and call
  `BLEDevice::startAdvertising()` from it. Without this, the module stops
  being reachable after the first disconnect.
- Buffer at most one in-flight event in your firmware. If notifications back
  up because the central isn't reading, drop new events rather than queuing
  them — the data is realtime.

## Reference sketches

| Folder                        | Pattern                                                        |
|-------------------------------|----------------------------------------------------------------|
| `../photogate_test/`          | Event-driven (ISR) + JSON events. Canonical example.            |
| `esp32_BLE_Server_Data_Output/` | Continuous sensor at 50 Hz + JSON events. Replace stub with real sensor read. |
| `esp32_beamBreak/`            | How to read an IR break-beam. No BLE.                          |
| `esp32_accel_degrees/`        | How to read the LSM303 + compute pitch/roll. No BLE.           |
| `esp32_find_MAC_address/`     | Utility to identify boards.                                    |

The `esp32_*` folders without BLE are scratch/learning sketches. The shipping
modules live next to `photogate_test/`.
