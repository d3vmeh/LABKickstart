"""BLE connection manager: discover, connect to, and stream from any
known LABKickstart module.

A `Profile` describes a device family (UUIDs + decoder + sample channel
names). The manager scans for advertisements whose name matches a known
profile, lets the UI connect/disconnect any of them, and pushes decoded
`Sample`s into the Hub's dispatch.

Adding support for a new module = one entry in PROFILES.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

from .sensors import Sample

log = logging.getLogger(__name__)


# ---------- Profiles ----------

@dataclass(frozen=True)
class Profile:
    name: str                                            # device-name match
    service_uuid: str
    char_uuid: str
    decoder: Callable[[bytes], Iterable[tuple[str, float]]]
    description: str = ""


def _decode_imu(data: bytes) -> Iterable[tuple[str, float]]:
    if len(data) != 20:
        return ()
    pitch, roll, ax, ay, az = struct.unpack("<5f", data)
    return (
        ("pitch_deg", pitch),
        ("roll_deg", roll),
        ("accel_x", ax),
        ("accel_y", ay),
        ("accel_z", az),
    )


def _decode_photogate_json(data: bytes) -> Iterable[tuple[str, float]]:
    try:
        obj = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ()
    ch = obj.get("channel")
    val = obj.get("value")
    if not isinstance(ch, str) or not isinstance(val, (int, float)):
        return ()
    return ((ch, float(val)),)


PROFILES: dict[str, Profile] = {
    "IMU_Module": Profile(
        name="IMU_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        char_uuid="2be54bb2-4e7d-4ac2-885d-c019bc130fea",
        decoder=_decode_imu,
        description="LSM303 accel: pitch/roll/accel_x/y/z",
    ),
    "LK-Photogate-A": Profile(
        name="LK-Photogate-A",
        service_uuid="5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f",
        char_uuid="5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f",
        decoder=_decode_photogate_json,
        description="Photogate A: emits gate_A_break_us events",
    ),
    "LK-Photogate-B": Profile(
        name="LK-Photogate-B",
        service_uuid="5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f",
        char_uuid="5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f",
        decoder=_decode_photogate_json,
        description="Photogate B: emits gate_B_break_us events",
    ),
}


# ---------- State ----------

@dataclass
class DeviceState:
    address: str
    name: str
    rssi: int | None = None
    profile_id: str | None = None
    connected: bool = False
    connecting: bool = False
    samples_received: int = 0
    last_seen: float = field(default_factory=time.time)
    error: str | None = None

    def to_json(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "rssi": self.rssi,
            "profile": self.profile_id,
            "connected": self.connected,
            "connecting": self.connecting,
            "samples": self.samples_received,
            "error": self.error,
        }


# ---------- Manager ----------

class BLEManager:
    """Owns BLE connections. Hub passes its dispatch callback at construction."""

    SCAN_TIMEOUT_S = 6.0

    def __init__(self, dispatch: Callable[[Sample], Awaitable[None] | None]):
        # Hub.dispatch(sample) - synchronous OK; we tolerate either.
        self._dispatch = dispatch
        # Address -> DeviceState (covers both scanned and connected)
        self._devices: dict[str, DeviceState] = {}
        # Address -> running asyncio task for the streaming connection
        self._tasks: dict[str, asyncio.Task] = {}
        self._stream_start = time.monotonic()

    # --- Read API ---

    def state(self) -> list[dict]:
        return [d.to_json() for d in self._devices.values()]

    # --- Public actions ---

    async def scan(self) -> list[dict]:
        try:
            from bleak import BleakScanner
        except ImportError as e:
            raise RuntimeError("bleak is not installed") from e

        log.info("[BLE] scan start (%.1fs)", self.SCAN_TIMEOUT_S)
        found = await BleakScanner.discover(timeout=self.SCAN_TIMEOUT_S, return_adv=True)
        now = time.time()
        # Only surface devices whose name matches a known profile.
        for addr, (dev, adv) in found.items():
            name = dev.name or ""
            if name not in PROFILES:
                continue
            existing = self._devices.get(addr)
            if existing:
                existing.rssi = adv.rssi
                existing.last_seen = now
                if not existing.connected:
                    existing.error = None
            else:
                self._devices[addr] = DeviceState(
                    address=addr, name=name, rssi=adv.rssi,
                    profile_id=name, last_seen=now,
                )
        log.info("[BLE] scan complete: %d known device(s)",
                 len([d for d in self._devices.values() if d.last_seen >= now - 1]))
        return self.state()

    async def connect(self, address: str) -> dict:
        if address in self._tasks and not self._tasks[address].done():
            raise RuntimeError("already connected or connecting")
        d = self._devices.get(address)
        if d is None:
            raise RuntimeError("unknown device; scan first")
        if d.profile_id is None or d.profile_id not in PROFILES:
            raise RuntimeError(f"no profile for {d.name}")
        d.connecting = True
        d.error = None
        task = asyncio.create_task(self._stream_one(address))
        self._tasks[address] = task
        return d.to_json()

    async def disconnect(self, address: str) -> dict:
        task = self._tasks.get(address)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        d = self._devices.get(address)
        if d is None:
            raise RuntimeError("unknown device")
        return d.to_json()

    async def shutdown(self) -> None:
        for addr in list(self._tasks):
            try:
                await self.disconnect(addr)
            except Exception:
                pass

    # --- Internals ---

    async def _stream_one(self, address: str) -> None:
        from bleak import BleakClient

        d = self._devices[address]
        profile = PROFILES[d.profile_id]
        log.info("[BLE] connecting to %s (%s)", d.name, address)
        try:
            async with BleakClient(address) as client:
                if not client.is_connected:
                    raise RuntimeError("connect returned but is_connected=False")

                def on_notify(_sender, data: bytearray):
                    t = time.monotonic() - self._stream_start
                    for ch, val in profile.decoder(bytes(data)):
                        d.samples_received += 1
                        try:
                            self._dispatch(Sample(d.address, t, ch, val))
                        except Exception as e:
                            log.warning("[BLE] dispatch error: %s", e)

                await client.start_notify(profile.char_uuid, on_notify)
                d.connected = True
                d.connecting = False
                log.info("[BLE] streaming %s", d.name)
                while client.is_connected:
                    await asyncio.sleep(0.5)
                log.info("[BLE] %s disconnected (link dropped)", d.name)
        except asyncio.CancelledError:
            log.info("[BLE] %s disconnected (by user)", d.name)
            raise
        except Exception as e:
            log.warning("[BLE] %s connection failed: %s", d.name, e)
            d.error = str(e)
        finally:
            d.connected = False
            d.connecting = False
            self._tasks.pop(address, None)
