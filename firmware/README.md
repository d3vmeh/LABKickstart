# LABKickstart firmware

ESP32 sketches for the sensor modules. One folder per module so each one is its
own Arduino sketch.

| Folder            | Purpose                                                     |
|-------------------|-------------------------------------------------------------|
| `photogate_test/` | One IR beam-break wired to one ESP32. Smoke-test for BLE.   |

## Building / flashing

Each folder is a standard Arduino sketch (folder name == `.ino` name).

1. Open the `.ino` file in Arduino IDE 2.x (or `arduino-cli compile`).
2. Boards Manager → install **esp32 by Espressif** (3.x).
3. Select your ESP32 board (e.g. *ESP32 Dev Module* or *DOIT ESP32 DEVKIT V1*).
4. Select the serial port the board enumerates as.
5. Upload.

The BLE stack is the one bundled with the ESP32 Arduino core — no extra
libraries required for the test module.

## On-air protocol (v0)

Every module advertises with a name prefixed `LK-` and exposes one BLE service
with a single notify+read characteristic that emits one event per JSON object,
e.g.:

```json
{"gate":"A","break_us":59917}
```

The Pi-side BLE client subscribes to this characteristic and turns each event
into the same `Sample` shape the rest of the codebase already uses
(`channel = "gate_A_break_us"`, `value = 59917`). That mapping happens on the
Pi, not on the ESP32 — keep the firmware dumb.

UUIDs (shared across photogate modules — only the device name distinguishes
gate A from gate B):

- Service: `5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f`
- Events:  `5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f`

## Smoke-testing from the Pi (or any computer with BLE)

A small CLI listener lives at `tools/ble_listen.py`. Use it to confirm the
ESP32 is advertising and emitting events before bringing up the full server.

```bash
pip install bleak
python tools/ble_listen.py --scan         # list LK-* devices in range
python tools/ble_listen.py                # connect to LK-Photogate-A and stream
python tools/ble_listen.py --name LK-Photogate-A
```

Wave your hand through the beam — every break should print a line:

```
[13:42:07] #1    gate=A break=58231 us  raw={"gate":"A","break_us":58231}
```

If `--scan` finds nothing: check the ESP32 has booted (serial monitor) and
that BLE isn't disabled on the host.
