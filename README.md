# LABKickstart

> An open, modular, IoT-enabled physics lab toolkit.
> 🥇 **1st place overall — IDEA Hacks 2026**

LABKickstart turns a laptop and a few $10 ESP32 boards into a complete physics
lab data-acquisition system. Each module reads one sensor and broadcasts over
Bluetooth LE; a Python web dashboard receives the streams, runs experiment-
specific derivations, plots live data, writes clean CSVs, and (optionally)
uses an LLM to convert teachers' existing lab handouts into student-facing
setup guides.

**No proprietary base station. No proprietary file format. No vendor lock-in.**

---

## Why

PASCO and Vernier have run school physics for 40 years. A $450 base station
before you buy a single sensor; locked connectors; locked file formats. A
district that has spent $30k on one vendor has to keep buying that vendor —
every locked connector is a moat.

A full LABKickstart kit costs less than one Vernier base station and unlocks
20+ standard physics experiments — Hooke's law, Atwood machines, projectile
motion, free fall, pendulums, collisions, friction, buoyancy.

Every line of firmware, every Python module, every CAD file is open source.
A teacher who has spent twenty years on PASCO can fork an experiment, modify
it for their classroom, and share it with the teacher next door — in twenty
minutes.

---

## Open hardware

All mechanical designs live in OnShape and are publicly viewable:

**🔗 [LABKickstart CAD on OnShape](https://cad.onshape.com/documents/6798fb3b1ef260424d103dd4/w/9adcb538dd3efbe956fa17f1/e/e2a2e2dccae245fef01fc912?renderMode=0&uiState=69eeae30a1b822cc550a4f74)**

Includes the photogate housings, IMU mounts, the ToF stand, and the modular
mounting rail that lets students reconfigure setups between experiments.
Fork the workspace, modify, export STLs, print, run.

Firmware (Arduino sketches per module) lives in [`firmware/`](firmware/).

---

## Architecture

```
┌─────────────────┐  BLE notify   ┌──────────────────┐    WebSocket   ┌──────────────┐
│ ESP32 module(s) │ ────────────> │ Python Hub       │ ─────────────> │ uPlot charts │
│  (one sensor    │   GATT char   │  · BLE manager   │                │ (vanilla JS) │
│   per board)    │               │  · Kit derive    │ ─── CSV ────>  │              │
└─────────────────┘               │  · Run + trigger │                │              │
                                  │  · LLM (teacher) │                │              │
                                  └──────────────────┘                └──────────────┘
```

- **Modules** ([`firmware/`](firmware/)) — Arduino sketches per sensor (photogate, IMU, ToF).
- **BLE manager** (`src/labkickstart/ble_manager.py`) — profile registry,
  auto-discovery of NOTIFY characteristics, per-connection stateful decoders.
- **Hub** (`src/labkickstart/app.py`) — single asyncio event loop. Fans every
  decoded sample to (1) the active run's CSV writer, (2) all WebSocket
  subscribers, and (3) the active kit's `derive()` function, which can emit
  additional physics-quantity samples back into the same fan-out.
- **Kits** (`src/labkickstart/kits.py`) — one Python class per experiment.
  Each declares `info`, `configure(params)`, `derive(sample)`, and the BLE
  modules it requires. Adding an experiment = adding one class.
- **Lab-guide LLM** (`src/labkickstart/lab_guides.py`) — gpt-4o-mini with
  schema-constrained output. Two flows: kit recommender (PDF → ranked kits)
  and student-facing setup guide.
- **Quicklook** (`src/labkickstart/quicklook.py`) — per-channel summary stats
  (count, mean, median, p5, p95, σ, σ/√N) computed from any run's CSV.
- **Frontend** (`src/labkickstart/static/`) — vanilla JS, uPlot, no build
  step. Per-device chart cards keep different sensor scales from crushing
  each other on a shared y-axis.

---

## Quickstart

Runs on macOS or a Raspberry Pi 4 (any host with Bluetooth and Python 3.11+).

```bash
# 1. Clone + install
git clone https://github.com/d3vmeh/LABKickstart
cd LABKickstart
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. (optional) AI features
echo "OPENAI_API_KEY=sk-..." > .env

# 3. Launch the dashboard
./dev.sh
# -> open http://localhost:8000
```

`dev.sh` injects `src/` onto `PYTHONPATH` and starts uvicorn with
`--reload`. Override host/port via env:

```bash
HOST=127.0.0.1 PORT=8001 ./dev.sh
```

### No hardware? Use a mock source

Set `LK_SENSOR` before launching to drive the UI from a built-in synthetic
sensor:

```bash
LK_SENSOR=imu       ./dev.sh   # mock IMU
LK_SENSOR=photogate ./dev.sh   # mock photogate
LK_SENSOR=tof       ./dev.sh   # mock ToF
```

---

## Hardware modules

Each module is an ESP32 plus one sensor, battery-powered for months between
charges. Current modules:

| Module             | Sensor               | Channels                                  |
|--------------------|----------------------|-------------------------------------------|
| `IMU_Module`       | LSM303 6-axis IMU    | `pitch_deg`, `roll_deg`, `accel_x/y/z`    |
| `BEAMBREAK_Module` | Dual IR photogate    | `gate_A_break_us`, `gate_B_break_us`      |
| `TOF_Module`       | VL53L0X laser ToF    | `distance_mm`                             |

Adding a new module = one entry in `PROFILES` (`src/labkickstart/ble_manager.py`)
+ one Arduino sketch in `firmware/`.

---

## Built-in kits

| Kit ID         | Experiment                          | Modules required               |
|----------------|-------------------------------------|--------------------------------|
| `sandbox`      | Any sensors, raw passthrough        | (any)                          |
| `photogate`    | Two-photogate kinematics            | `BEAMBREAK_Module`             |
| `imu`          | IMU monitor (tilt, free-fall)       | `IMU_Module`                   |
| `imu_sinusoid` | Band-pass smoothed oscillations     | `IMU_Module`                   |
| `tof`          | Distance monitor + auto-stop        | `TOF_Module`                   |
| `shm`          | SHM with cross-sensor verification  | `TOF_Module`, `IMU_Module`     |

### Adding a new kit

```python
class MyKit:
    info = KitInfo(
        id="my_kit",
        name="My Experiment",
        description="...",
        params=[KitParam("foo", "Foo", "m", default=1.0)],
        modules=["IMU_Module"],
    )

    def configure(self, params): ...
    def derive(self, sample) -> Iterable[Sample]: ...
```

Then register it in `build_registry()`. That's the whole framework.

---

## AI features (opt-in)

Both require `OPENAI_API_KEY`. Both use `gpt-4o-mini` with schema-constrained
output. Both cache results to disk. Cost is ~$0.001 per call.

- **Lab-guide generator** — upload a teacher's existing PDF, get a structured
  materials list + numbered student steps, with a "why" sentence per step
  that explains the underlying physics or measurement reason.
- **Kit recommender** — same PDF, GPT picks the best-matching kit from a
  closed enum of registry IDs (cannot hallucinate a kit). Returns rationale,
  confidence, and the physical modules required (server-injected from the
  registry, not LLM-generated).

If the env key is unset, both features return HTTP 503 and the rest of the
dashboard runs unaffected.

---

## API

| Method | Path                                    | Purpose                          |
|--------|-----------------------------------------|----------------------------------|
| GET    | `/`                                     | Dashboard                        |
| GET    | `/api/devices`                          | List connected + scanned devices |
| POST   | `/api/ble/scan`                         | Trigger a BLE scan               |
| POST   | `/api/ble/connect/{address}`            | Connect to a discovered device   |
| POST   | `/api/ble/disconnect/{address}`         | Disconnect                       |
| GET    | `/api/kits`                             | List kits + active selection     |
| POST   | `/api/kit`                              | Apply a kit                      |
| POST   | `/api/kits/recommend`                   | LLM kit recommender (from PDF)   |
| POST   | `/api/kits/{id}/lab_guide`              | Generate a student lab guide     |
| POST   | `/api/arm`                              | Start a run                      |
| POST   | `/api/stop`                             | Stop the active run              |
| GET    | `/api/runs`                             | List runs + active state         |
| GET    | `/api/runs/{id}/csv`                    | Download a run's CSV             |
| GET    | `/api/runs/{id}/quicklook`              | Per-channel summary stats        |
| WS     | `/ws/stream`                            | Live sample stream               |

Every WebSocket message is a JSON object: `{"device_id", "t", "channel", "value"}`,
or `{"type": "run_state", "active": ...}` for run lifecycle events.

---

## Repository layout

```
LABKickstart/
├── firmware/                  # ESP32 Arduino sketches (one per module)
│   ├── device_interfaces/
│   └── photogate_test/
├── src/labkickstart/
│   ├── app.py                 # FastAPI app + Hub (asyncio fan-out)
│   ├── ble_manager.py         # BLE profile registry + connection manager
│   ├── kits.py                # Kit registry (each experiment is a class)
│   ├── lab_guides.py          # LLM: lab-guide generator + kit recommender
│   ├── quicklook.py           # Per-run summary stats
│   ├── runs.py                # Run/CSV lifecycle + auto-stop triggers
│   ├── sensors.py             # Sample dataclass + mock sources
│   └── static/                # Dashboard (HTML + vanilla JS + uPlot)
├── docs/
├── data/                      # Run CSVs (gitignored)
├── dev.sh
├── requirements.txt
└── pyproject.toml
```

---

## Roadmap

- Force, optical, and magnetic-field modules (open-hardware spec, same kit framework)
- Kit marketplace — teachers publish their own Kit classes
- Firmware OTA from the dashboard so teachers don't touch the Arduino IDE
- Classroom pilot, fall 2026

---

## License

- **Software** (everything under `src/`, `firmware/`): Apache License 2.0
- **Hardware designs** (OnShape document linked above + future exports): CERN-OHL-S v2

Apache 2.0 is permissive: you can use, modify, and redistribute the software
freely, including commercially, with an explicit patent grant from contributors.
CERN-OHL-S is the hardware analog of GPL: forks of the CAD can be manufactured
freely, but modified designs that are redistributed must remain open under the
same license — improvements flow back to the community.

See `LICENSE` (Apache 2.0) for software, `LICENSE-HARDWARE` (CERN-OHL-S v2)
for hardware designs.

---

## Acknowledgements

Built at **IDEA Hacks 2026**. Thanks to the organizers, mentors, and every
teacher who has worked around proprietary lab equipment for the past forty
years.
