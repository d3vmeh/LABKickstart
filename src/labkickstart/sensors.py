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
    """Emits a sine wave on one synthetic device, ~50 Hz."""

    def __init__(self, device_id: str = "mock-01", name: str = "MockESP32", hz: float = 50.0):
        self._info = DeviceInfo(device_id=device_id, name=name, rssi=-42, connected=True)
        self._period = 1.0 / hz

    def devices(self) -> list[DeviceInfo]:
        return [self._info]

    async def stream(self) -> AsyncIterator[Sample]:
        start = time.monotonic()
        while True:
            t = time.monotonic() - start
            # Two channels so the chart has something to compare
            yield Sample(self._info.device_id, t, "ax", math.sin(2 * math.pi * 0.5 * t))
            yield Sample(self._info.device_id, t, "ay", math.cos(2 * math.pi * 0.5 * t))
            await asyncio.sleep(self._period)
