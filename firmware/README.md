# LABKickstart firmware

ESP32 sketches for the sensor modules. One folder per module so each one is its
own Arduino sketch.

| Folder                | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `photogate_test/`     | One IR beam-break wired to one ESP32. Smoke-test for BLE.|
| `device_interfaces/`  | Reference sketches and the project-wide BLE convention.  |

The wire protocol every module follows is documented in
[`device_interfaces/README.md`](device_interfaces/README.md). Read that
before writing a new module.

## Building / flashing

Each folder is a standard Arduino sketch (folder name == `.ino` name).

1. Open the `.ino` file in Arduino IDE 2.x (or `arduino-cli compile`).
2. Boards Manager → install **esp32 by Espressif** (3.x).
3. Select your ESP32 board (e.g. *ESP32 Dev Module* or *DOIT ESP32 DEVKIT V1*).
4. Select the serial port the board enumerates as.
5. Upload.

The BLE stack is the one bundled with the ESP32 Arduino core — no extra
libraries required for the photogate module. The IMU example sketch needs
the **Adafruit LSM303 Accel** + **Adafruit Unified Sensor** libraries from
the Library Manager.

## On-air protocol (one-line summary)

- Device name: `LK-<Module>-<id>` (e.g. `LK-Photogate-A`)
- Service UUID: `5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f`
- Events char:  `5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f` (notify)
- Each notification: `{"channel":"<name>","value":<number>}`

Full spec, channel naming rules, cadence guidance:
[`device_interfaces/README.md`](device_interfaces/README.md).

## Smoke-testing from any computer with BLE

A small CLI listener lives at `tools/ble_listen.py`.

```bash
pip install bleak
python tools/ble_listen.py --scan          # list LK-* devices in range
python tools/ble_listen.py                 # connect to LK-Photogate-A and stream
python tools/ble_listen.py --name LK-IMU-01
```

You should see one line per event:

```
[13:42:07] #1    gate_A_break_us=58231
[13:42:09] #2    pitch_deg=37.4
```

If `--scan` finds nothing: check the ESP32 has booted (serial monitor) and
that BLE isn't disabled on the host.
