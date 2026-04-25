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
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

from .sensors import Sample

log = logging.getLogger(__name__)


# ---------- Profiles ----------

Decoder = Callable[[bytes], Iterable[tuple[str, float]]]


@dataclass(frozen=True)
class Profile:
    name: str                                            # device-name match
    service_uuid: str
    char_uuid: str | None                                # None = auto-discover first NOTIFY
    # Per-connection decoder factory. Called once at connect time so the
    # decoder can hold state (e.g. last-BLOCKED timestamps per gate) without
    # leaking across reconnections.
    decoder: Callable[[], Decoder]
    description: str = ""


def _stateless(decoder: Decoder) -> Callable[[], Decoder]:
    """Wrap a stateless decoder so it fits the factory signature."""
    return lambda: decoder


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


def _decode_tof_distance(data: bytes) -> Iterable[tuple[str, float]]:
    """Length-based heuristic, mirroring the teammate's tof_ble_receiver.py
    while the firmware is still being finalized. Once the real ESP32 sketch
    commits to one format, replace this with a single-format decoder.
    """
    # 1) UTF-8 string like "123.45"
    try:
        text = data.decode("utf-8").strip()
        return (("distance_mm", float(text)),)
    except (UnicodeDecodeError, ValueError):
        pass
    # 2) uint16 little-endian (2 bytes, common for VL53L0X)
    if len(data) == 2:
        v, = struct.unpack("<H", data)
        return (("distance_mm", float(v)),)
    # 3) 4 bytes -> try float32 first, fall back to uint32
    if len(data) == 4:
        f, = struct.unpack("<f", data)
        if -1000.0 < f < 10000.0:
            return (("distance_mm", f),)
        u, = struct.unpack("<I", data)
        return (("distance_mm", float(u)),)
    return ()


def _make_beambreak_decoder() -> Decoder:
    """Stateful decoder for the BEAMBREAK_Module: pairs each BLOCKED with its
    next CLEAR per gate, emits `gate_A_break_us` / `gate_B_break_us` with the
    duration in microseconds. PhotogateKit consumes those channels directly.

    Wire format (per BLE notification): 6 bytes packed `<BBI`:
        gate_id (uint8, 1 or 2), state (uint8, 1=BLOCKED 0=CLEAR), timestamp_us (uint32)
    """
    last_blocked_us: dict[int, int] = {}

    def decode(data: bytes):
        if len(data) != 6:
            return ()
        gate_id, state, ts_us = struct.unpack("<BBI", data)
        label = {1: "A", 2: "B"}.get(gate_id)
        if label is None:
            return ()
        if state == 1:
            # BLOCKED: remember when, wait for CLEAR.
            last_blocked_us[gate_id] = ts_us
            return ()
        # CLEAR: emit duration if we saw the matching BLOCKED.
        start = last_blocked_us.pop(gate_id, None)
        if start is None:
            return ()
        dur = ts_us - start
        if dur < 0:
            dur += 2 ** 32  # micros() overflow (~71 min)
        return ((f"gate_{label}_break_us", float(dur)),)

    return decode


PROFILES: dict[str, Profile] = {
    "IMU_Module": Profile(
        name="IMU_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        char_uuid="2be54bb2-4e7d-4ac2-885d-c019bc130fea",
        decoder=_stateless(_decode_imu),
        description="LSM303 accel: pitch/roll/accel_x/y/z",
    ),
    "BEAMBREAK_Module": Profile(
        name="BEAMBREAK_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        char_uuid="7c2b6f3a-4a8c-4d24-8f8b-32e2a5c76f10",
        decoder=_make_beambreak_decoder,
        description="Two-gate photogate: pairs BLOCKED/CLEAR into gate_A/B_break_us",
    ),
    "TOF_Module": Profile(
        name="TOF_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        # The teammate's firmware hasn't committed to a characteristic UUID
        # yet (their receiver still has PUT_YOUR_TOF_DISTANCE_UUID_HERE).
        # `None` tells the manager to auto-discover the first NOTIFY char
        # on the device. Replace with a real UUID once the firmware lands.
        char_uuid=None,
        decoder=_stateless(_decode_tof_distance),
        description="Time-of-Flight sensor: distance_mm",
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
        self._dispatch = dispatch
        self._devices: dict[str, DeviceState] = {}
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

    @staticmethod
    def _discover_notify_char(client) -> str:
        """Pick the first NOTIFY-capable characteristic on the device.
        Used when a profile leaves char_uuid unspecified."""
        for svc in client.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties:
                    log.info("[BLE] auto-selected NOTIFY char %s", ch.uuid)
                    return ch.uuid
        raise RuntimeError("no NOTIFY characteristics found on device")

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
        decoder = profile.decoder()  # fresh per-connection decoder (may hold state)
        log.info("[BLE] connecting to %s (%s)", d.name, address)
        try:
            async with BleakClient(address) as client:
                if not client.is_connected:
                    raise RuntimeError("connect returned but is_connected=False")

                def on_notify(_sender, data: bytearray):
                    t = time.monotonic() - self._stream_start
                    for ch, val in decoder(bytes(data)):
                        d.samples_received += 1
                        try:
                            self._dispatch(Sample(d.address, t, ch, val))
                        except Exception as e:
                            log.warning("[BLE] dispatch error: %s", e)

                char_uuid = profile.char_uuid or self._discover_notify_char(client)
                await client.start_notify(char_uuid, on_notify)
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
