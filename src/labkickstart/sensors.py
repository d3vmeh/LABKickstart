from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class Sample:
    device_id: str
    t: float          # seconds since run start
    channel: str      # e.g. "ax", "gate"
    value: float


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    rssi: int | None = None
    connected: bool = False


class SensorSource(Protocol):
    """A source of sensor samples. v0 = MockSensor; later = BLESensor."""

    def devices(self) -> list[DeviceInfo]: ...

    def stream(self) -> AsyncIterator[Sample]:
        """Yield samples forever until cancelled."""
        ...


class MockSensor:
    """Emits a sine wave on one synthetic device, ~50 Hz. Useful for chart smoke tests."""

    def __init__(self, device_id: str = "mock-01", name: str = "MockESP32", hz: float = 50.0):
        self._info = DeviceInfo(device_id=device_id, name=name, rssi=-42, connected=True)
        self._period = 1.0 / hz

    def devices(self) -> list[DeviceInfo]:
        return [self._info]

    async def stream(self) -> AsyncIterator[Sample]:
        start = time.monotonic()
        while True:
            t = time.monotonic() - start
            yield Sample(self._info.device_id, t, "ax", math.sin(2 * math.pi * 0.5 * t))
            yield Sample(self._info.device_id, t, "ay", math.cos(2 * math.pi * 0.5 * t))
            await asyncio.sleep(self._period)


class MockIMUSensor:
    """Simulates the LSM303 IMU module's data stream.

    The real ESP32 IMU module (firmware/device_interfaces/modules/
    esp32_IMU_module_transmitter) ships a 20-byte packed struct of five
    little-endian float32s every 20 ms. The (future) Pi-side adapter will
    unpack each notification into these five `Sample`s; we emit the same
    shape here so the rest of the system is testable without hardware.

    Channels:
        pitch_deg   - degrees, -90 .. +90    (gentle slow sweep + noise)
        roll_deg    - degrees, -180 .. +180  (gentle slow sweep + noise)
        accel_x     - m/s^2, small jitter around 0
        accel_y     - m/s^2, small jitter around 0
        accel_z     - m/s^2, around -9.81 when "level" (gravity)
    """

    def __init__(
        self,
        device_id: str = "imu-01",
        name: str = "MockIMU",
        hz: float = 50.0,
    ):
        self._info = DeviceInfo(device_id=device_id, name=name, rssi=-55, connected=True)
        self._period = 1.0 / hz

    def devices(self) -> list[DeviceInfo]:
        return [self._info]

    async def stream(self) -> AsyncIterator[Sample]:
        import random
        start = time.monotonic()
        while True:
            t = time.monotonic() - start
            # Slow sinusoidal tilt so a chart over a few seconds shows motion.
            pitch_deg = 15.0 * math.sin(2 * math.pi * 0.1 * t) + random.uniform(-0.2, 0.2)
            roll_deg = 25.0 * math.sin(2 * math.pi * 0.07 * t + 0.5) + random.uniform(-0.2, 0.2)
            # Decompose g (~9.81 m/s^2) onto board axes given the simulated
            # tilt, so accel components stay self-consistent with pitch/roll.
            g = 9.81
            p = math.radians(pitch_deg)
            r = math.radians(roll_deg)
            accel_x = -g * math.sin(p) + random.uniform(-0.05, 0.05)
            accel_y = g * math.sin(r) * math.cos(p) + random.uniform(-0.05, 0.05)
            accel_z = -g * math.cos(r) * math.cos(p) + random.uniform(-0.05, 0.05)
            yield Sample(self._info.device_id, t, "pitch_deg", pitch_deg)
            yield Sample(self._info.device_id, t, "roll_deg", roll_deg)
            yield Sample(self._info.device_id, t, "accel_x", accel_x)
            yield Sample(self._info.device_id, t, "accel_y", accel_y)
            yield Sample(self._info.device_id, t, "accel_z", accel_z)
            await asyncio.sleep(self._period)


class MockPhotogateSensor:
    """Simulates the *raw* events a real two-photogate ESP32 would emit.

    The ESP32 reports beam-break events only:
        channel = "gate_A_break_us" | "gate_B_break_us"
        value   = beam-break duration in microseconds
        t       = timestamp at which the beam rose (end of break)

    All physics (velocity, acceleration) is left to the kit running on the Pi.
    The mock simulates a cart that starts at rest and accelerates past gate A,
    then gate B, with a small jitter and tiny measurement noise.
    """

    def __init__(
        self,
        device_id: str = "photogates-01",
        name: str = "MockPhotogates",
        d_A: float = 0.20,
        d_AB: float = 0.50,
        flag_w: float = 0.05,
        a_mean: float = 1.5,
        a_jitter: float = 0.3,
        period_s: float = 3.0,
    ):
        self._info = DeviceInfo(device_id=device_id, name=name, rssi=-48, connected=True)
        self.d_A = d_A
        self.d_AB = d_AB
        self.flag_w = flag_w
        self.a_mean = a_mean
        self.a_jitter = a_jitter
        self.period_s = period_s

    def devices(self) -> list[DeviceInfo]:
        return [self._info]

    async def stream(self) -> AsyncIterator[Sample]:
        import random
        start = time.monotonic()
        await asyncio.sleep(1.0)
        while True:
            a = self.a_mean + random.uniform(-self.a_jitter, self.a_jitter)
            v_A = math.sqrt(2 * a * self.d_A)
            v_B = math.sqrt(2 * a * (self.d_A + self.d_AB))
            # Beam-break durations: how long the flag occludes the beam.
            break_A_us = (self.flag_w / v_A) * 1_000_000.0
            break_B_us = (self.flag_w / v_B) * 1_000_000.0
            # Small clock jitter (real ESP32 timer is far more precise than this).
            break_A_us *= 1.0 + random.uniform(-0.005, 0.005)
            break_B_us *= 1.0 + random.uniform(-0.005, 0.005)
            # Time the cart spends traversing d_AB at the (changing) velocity.
            dt_AB = (v_B - v_A) / a
            t0 = time.monotonic() - start  # rising-edge time at gate A
            tB = t0 + dt_AB                 # rising-edge time at gate B
            yield Sample(self._info.device_id, t0, "gate_A_break_us", break_A_us)
            yield Sample(self._info.device_id, tB, "gate_B_break_us", break_B_us)
            await asyncio.sleep(self.period_s)
