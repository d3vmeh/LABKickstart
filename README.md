# LABKickstart

Modular physics lab hub. Architecture:

- **Pi 4** — server hub. Runs FastAPI + BLE central. Saves CSVs to `data/runs/`.
- **ESP32 nodes** — BLE peripherals streaming sensor samples (photogate, IMU, load cell).
- **Mac/laptop** — opens the Pi's web UI in a browser over Wi-Fi.

The v0 ships with a `MockSensor` so the whole UI works on a laptop with no hardware.

## Run on Mac (dev)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/uvicorn labkickstart.app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000.

If `.venv/bin/python -c "import labkickstart"` fails after `pip install -e .`,
re-run `.venv/bin/pip install --force-reinstall --no-deps -e .` (a hatchling
editable install can land with a malformed `.pth` file on first install).

## API

| Method | Path                       | Notes                                  |
|--------|----------------------------|----------------------------------------|
| GET    | `/`                        | Dashboard                              |
| GET    | `/api/devices`             | Connected sensor nodes                 |
| GET    | `/api/runs`                | Active run + history                   |
| POST   | `/api/arm` `{name}`        | Start a run                            |
| POST   | `/api/stop`                | Stop the active run                    |
| GET    | `/api/runs/{run_id}/csv`   | Download CSV                           |
| WS     | `/ws/stream`               | Live sample stream (JSON per sample)   |

Each sample on the WebSocket: `{"device_id", "t", "channel", "value"}`.

## Layout

```
src/labkickstart/
  app.py           FastAPI app, routes, WebSocket, Hub orchestrator
  sensors.py       SensorSource protocol + MockSensor (sine wave, 50 Hz)
  runs.py          RunStore: CSV writer, history listing
  static/          index.html, app.js (vanilla JS + uPlot via CDN)
data/runs/         Saved CSVs (gitignored)
```

## Next

- `BLESensor` implementation using `bleak` to receive ESP32 BLE notifications.
- ESP32 firmware (separate dir) with photogate timing characteristic.
- Pi deploy: same commands; bind on `0.0.0.0`; systemd unit for auto-start.
