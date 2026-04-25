"""Experiment kits: pair a sensor topology with a derivation function and a
parameter schema. The ESP32 only ever sends raw events; the kit running on the
Pi turns those into physics quantities the student cares about.
"""
from __future__ import annotations

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
class KitInfo:
    id: str
    name: str
    description: str
    params: list[KitParam]

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "params": [p.to_json() for p in self.params]}


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


# Registry. Add new kits here as classes are written.
def build_registry() -> dict[str, Kit]:
    return {"photogate": PhotogateKit()}
