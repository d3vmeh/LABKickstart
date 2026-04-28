# tools/

Standalone scripts that don't ship with the dashboard. Useful during
hardware bring-up or debugging.

## `ble_listen.py`

Connect to a LABKickstart ESP32 over BLE and print raw notifications.
Confirms a module is advertising and streaming before you involve the
full server.

```bash
# scan only
python tools/ble_listen.py --scan

# connect + stream by name
python tools/ble_listen.py --name IMU_Module

# connect + stream by address
python tools/ble_listen.py --address AA:BB:CC:DD:EE:FF
```

Auto-discovers the first NOTIFY-able characteristic on the device, so
it works for any module that follows the LABKickstart BLE convention.
