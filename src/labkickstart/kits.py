"""Experiment kits: pair a sensor topology with a derivation function and a
parameter schema. The ESP32 only ever sends raw events; the kit running on the
Pi turns those into physics quantities the student cares about.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .sensors import Sample


@dataclass
class KitParam:
    key: str
    label: str
    unit: str
    default: float
    required: bool = True

    def to_json(self) -> dict:
        return {"key": self.key, "label": self.label, "unit": self.unit,
                "default": self.default, "required": self.required}


@dataclass
class KitDiagram:
    title: str
    url: str  # served by the static mount, e.g. "/static/diagrams/photogate-wiring.svg"
    caption: str = ""

    def to_json(self) -> dict:
        return {"title": self.title, "url": self.url, "caption": self.caption}


@dataclass(frozen=True)
class Trigger:
    """A run-time condition the student can enable when arming.
    When the condition fires, the active run stops (and the CSV closes
    with the triggering sample as its last row)."""
    id: str
    label: str
    channel: str
    unit: str
    direction: str        # "below" | "above"
    default_value: float

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "channel": self.channel,
            "unit": self.unit,
            "direction": self.direction,
            "default_value": self.default_value,
        }


@dataclass
class KitInfo:
    id: str
    name: str
    description: str
    params: list[KitParam]
    diagrams: list[KitDiagram] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "params": [p.to_json() for p in self.params],
                "diagrams": [d.to_json() for d in self.diagrams],
                "triggers": [t.to_json() for t in self.triggers]}


class Kit(Protocol):
    info: KitInfo
    def configure(self, params: dict) -> None: ...
    def derive(self, sample: Sample) -> Iterable[Sample]: ...


class PhotogateKit:
    """Two photogates on a track. Raw events from the ESP32:
        channel = "gate_A_break_us" | "gate_B_break_us"
        value   = beam-break duration in microseconds
        t       = timestamp at which the beam rose (end of break)

    Derived per pass through the gate pair:
        v_A    (m/s)  - instantaneous velocity at gate A    [needs flag_w]
        v_B    (m/s)  - instantaneous velocity at gate B    [needs flag_w]
        v_avg  (m/s)  - average velocity between gates       [always]
        a      (m/s²) - acceleration                        [needs both v_A, v_B]
    """

    info = KitInfo(
        id="photogate",
        name="Two-Photogate Kinematics",
        description=(
            "Cart passes two IR-beam photogates on a track. Computes velocity at "
            "each gate (if a flag width is supplied) plus average velocity and "
            "acceleration between gates."
        ),
        params=[
            KitParam("d_AB", "Distance between gates", "m", default=0.50, required=True),
            KitParam("flag_w", "Flag / cart width", "m", default=0.05, required=False),
        ],
        diagrams=[
            KitDiagram(
                title="Experiment setup",
                url="/static/diagrams/photogate-track.svg",
                caption=(
                    "A cart with a flag passes between two photogates. The flag breaks each "
                    "beam as it passes through; the IR emitter sits on top of each gate post "
                    "and the receiver below (or vice versa). d_AB and flag_w are the two "
                    "measurements you provide."
                ),
            ),
        ],
    )

    def __init__(self) -> None:
        self.d_AB: float | None = None
        self.flag_w: float | None = None
        # Pending gate-A pass: timestamp of the rising edge and v_A (or None).
        self._pending_A: tuple[float, float | None] | None = None

    def configure(self, params: dict) -> None:
        if "d_AB" not in params:
            raise ValueError("d_AB is required")
        d = float(params["d_AB"])
        if d <= 0:
            raise ValueError("d_AB must be positive")
        self.d_AB = d
        flag = params.get("flag_w")
        self.flag_w = float(flag) if flag not in (None, "", 0) else None
        self._pending_A = None  # reset state when reconfigured

    def derive(self, sample: Sample) -> Iterable[Sample]:
        if self.d_AB is None:
            return  # not configured; pass-through only
        ch = sample.channel
        if ch == "gate_A_break_us":
            v_A = self._velocity_from_break_us(sample.value)
            # Two A breaks back-to-back: the cart never reached B.
            # If the previous A was very recent (<200 ms), assume a flag
            # wobble and keep the FIRST A's timestamp (more accurate edge).
            # Otherwise replace - the previous pass is stale.
            if self._pending_A is not None:
                if sample.t - self._pending_A[0] > 0.2:
                    self._pending_A = (sample.t, v_A)
                # else keep the older _pending_A
            else:
                self._pending_A = (sample.t, v_A)
            if v_A is not None:
                yield Sample(sample.device_id, sample.t, "v_A (m/s)", v_A)
        elif ch == "gate_B_break_us":
            v_B = self._velocity_from_break_us(sample.value)
            if v_B is not None:
                yield Sample(sample.device_id, sample.t, "v_B (m/s)", v_B)
            if self._pending_A is not None:
                tA, v_A = self._pending_A
                dt = sample.t - tA
                if dt > 0:
                    v_avg = self.d_AB / dt
                    yield Sample(sample.device_id, sample.t, "v_avg (m/s)", v_avg)
                if v_A is not None and v_B is not None:
                    a = (v_B * v_B - v_A * v_A) / (2 * self.d_AB)
                    yield Sample(sample.device_id, sample.t, "a (m/s²)", a)
                self._pending_A = None

    def _velocity_from_break_us(self, break_us: float) -> float | None:
        if self.flag_w is None or break_us <= 0:
            return None
        return self.flag_w / (break_us / 1_000_000.0)


class IMUKit:
    """A bare-bones experiment for the LSM303 IMU module.

    No derivations - the IMU module already ships pitch, roll, and three
    acceleration components computed on-device. The kit exists so a student
    can apply it (Arm requires a kit) and so the UI shows context for what
    the channels mean. Future kits can add derivations (e.g. a pendulum kit
    that derives period from accel_x oscillations).
    """

    info = KitInfo(
        id="imu",
        name="IMU module monitor",
        description=(
            "Stream pitch, roll, and the three acceleration components from a "
            "single IMU module. Useful for tilt experiments, free-fall detection, "
            "and pendulums. The CSV captures all five channels at the module's "
            "native rate."
        ),
        params=[],
        diagrams=[],
    )

    def configure(self, params: dict) -> None:
        # Nothing to configure for v0.
        return

    def derive(self, sample: Sample) -> Iterable[Sample]:
        return ()


class ToFKit:
    """Time-of-Flight distance monitor.

    No derivations in v0 - the kit just provides experiment context for
    the single `distance_mm` channel. Future versions could derive
    instantaneous velocity from successive samples.
    """

    info = KitInfo(
        id="tof",
        name="ToF distance monitor",
        description=(
            "Stream distance from a Time-of-Flight sensor. Useful for free-fall "
            "drops, pendulums, and anything where a single 1-D distance vs. time "
            "trace is enough. The CSV captures distance_mm at the module's "
            "native rate."
        ),
        params=[],
        diagrams=[],
        triggers=[
            Trigger(
                id="auto_stop_below",
                label="Auto-stop when distance falls below",
                channel="distance_mm",
                unit="mm",
                direction="below",
                default_value=150.0,
            ),
        ],
    )

    def configure(self, params: dict) -> None:
        return

    def derive(self, sample: Sample) -> Iterable[Sample]:
        return ()


class SHMKit:
    """Simple harmonic motion of a mass between two springs.

    Subscribes to `distance_mm` (from the ToF below the mass). Detects
    peaks and troughs in the distance trace, derives oscillation period,
    amplitude, and angular frequency once per cycle, and predicts the
    IMU's `accel_z` at every incoming distance sample so the two sensors
    can be cross-checked visually.

    The IMU's actual `accel_z` is not consumed by this kit — it streams
    to its own chart card unchanged, with a gravity baseline of about
    -9.81 m/s² included. Compare the *waveform* (period and amplitude)
    of the IMU trace and the predicted trace; equal shape means SHM
    holds and the sensors agree.

    See docs/superpowers/specs/2026-04-25-shm-kit-design.md for the full
    derivation contract.
    """

    info = KitInfo(
        id="shm",
        name="SHM on springs",
        description=(
            "Mass suspended between two springs, oscillating vertically. "
            "ToF below the mass measures distance; IMU on the mass measures "
            "vertical acceleration. Computes period, amplitude, and angular "
            "frequency in real time, and predicts the IMU's accel_z from the "
            "ToF data so the two sensors can be cross-checked."
        ),
        params=[],
        diagrams=[],
    )

    PEAK_LOOKBACK = 5                # samples on each side
    BUFFER_SIZE = 4 * PEAK_LOOKBACK  # bounded
    MIN_PERIOD_S = 0.05
    MAX_PERIOD_S = 30.0
    MAX_AMPLITUDE_MM = 10000.0
    PERIOD_HISTORY = 3

    def __init__(self) -> None:
        self._buf: deque[tuple[float, float]] = deque(maxlen=self.BUFFER_SIZE)
        self._last_peak: tuple[float, float] | None = None        # (t, value)
        self._last_trough: tuple[float, float] | None = None
        self._equilibrium_mm: float | None = None
        self._period_history: deque[float] = deque(maxlen=self.PERIOD_HISTORY)
        self._omega_smoothed: float | None = None

    def configure(self, params: dict) -> None:
        # Reset all running state so a re-applied kit doesn't pair pre-arm
        # samples with post-arm ones.
        self._buf.clear()
        self._last_peak = None
        self._last_trough = None
        self._equilibrium_mm = None
        self._period_history.clear()
        self._omega_smoothed = None

    def derive(self, sample: Sample) -> Iterable[Sample]:
        if sample.channel != "distance_mm":
            return ()

        self._buf.append((sample.t, sample.value))

        emitted: list[Sample] = []
        N = self.PEAK_LOOKBACK

        # Confirm the candidate at index (len - N - 1): it has N samples after it.
        if len(self._buf) >= 2 * N + 1:
            idx = len(self._buf) - N - 1
            cand_t, cand_v = self._buf[idx]
            before = [self._buf[i][1] for i in range(idx - N, idx)]
            after = [self._buf[i][1] for i in range(idx + 1, idx + N + 1)]

            # Strict on the "before" side, non-strict on "after" — breaks the
            # tie when two adjacent samples straddle the true peak/trough and
            # land at exactly equal values (common for clean sinusoids).
            if all(cand_v > b for b in before) and all(cand_v >= a for a in after):
                self._on_peak(cand_t, cand_v, sample.device_id, emitted)
            elif all(cand_v < b for b in before) and all(cand_v <= a for a in after):
                self._on_trough(cand_t, cand_v, sample.device_id, emitted)

        # Per-sample prediction once we have ω and an equilibrium estimate.
        if self._omega_smoothed is not None and self._equilibrium_mm is not None:
            displacement_m = (sample.value - self._equilibrium_mm) / 1000.0
            accel_predicted = -(self._omega_smoothed ** 2) * displacement_m
            emitted.append(Sample(
                sample.device_id, sample.t,
                "accel_z_predicted", accel_predicted,
            ))

        return emitted

    def _on_peak(self, t: float, v: float, device_id: str, out: list[Sample]) -> None:
        if self._last_peak is not None:
            period = t - self._last_peak[0]
            if self.MIN_PERIOD_S < period < self.MAX_PERIOD_S:
                out.append(Sample(device_id, t, "period_s", period))
                out.append(Sample(device_id, t, "omega_rad_s", 2 * math.pi / period))
                self._period_history.append(period)
                self._omega_smoothed = self._smoothed_omega()
        self._last_peak = (t, v)
        self._update_equilibrium()

    def _on_trough(self, t: float, v: float, device_id: str, out: list[Sample]) -> None:
        if self._last_peak is not None:
            amp = (self._last_peak[1] - v) / 2.0
            if 0.0 < amp < self.MAX_AMPLITUDE_MM:
                out.append(Sample(device_id, t, "amplitude_mm", amp))
        self._last_trough = (t, v)
        self._update_equilibrium()

    def _update_equilibrium(self) -> None:
        if self._last_peak is not None and self._last_trough is not None:
            self._equilibrium_mm = (self._last_peak[1] + self._last_trough[1]) / 2.0

    def _smoothed_omega(self) -> float:
        # Median of the period history (or whatever's available).
        sorted_p = sorted(self._period_history)
        n = len(sorted_p)
        if n == 0:
            return 0.0
        if n % 2 == 1:
            median = sorted_p[n // 2]
        else:
            median = (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2.0
        return 2 * math.pi / median


# Registry. Add new kits here as classes are written.
def build_registry() -> dict[str, Kit]:
    return {
        "photogate": PhotogateKit(),
        "imu": IMUKit(),
        "tof": ToFKit(),
        "shm": SHMKit(),
    }
