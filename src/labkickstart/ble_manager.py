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
    name: str                                            # exact device-name match
    service_uuid: str
    char_uuid: str | None                                # None = auto-discover first NOTIFY
    # Per-connection decoder factory. Called once at connect time so the
    # decoder can hold state (e.g. last-BLOCKED timestamps per gate) without
    # leaking across reconnections.
    decoder: Callable[[], Decoder]
    description: str = ""
    # Optional prefix: when set, any advertised name starting with this
    # also matches this profile (e.g. BEAMBREAK_Module_2 -> BEAMBREAK_Module).
    name_prefix: str | None = None


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
    """Decode the TOF_Module's 5-byte packed struct:
        <f distance_mm, B status (0=valid, 1=invalid)>
    Invalid readings (out-of-range / sensor error) are dropped so the
    chart isn't polluted with sentinel values like -1.
    """
    if len(data) != 5:
        return ()
    distance_mm, status = struct.unpack("<fB", data)
    # Drop firmware-flagged invalid frames AND any negative distance (defensive
    # in case the firmware ever sends status=0 with the -1 sentinel).
    if status != 0 or distance_mm < 0:
        return ()
    return (("distance_mm", distance_mm),)


def _make_beambreak_decoder() -> Decoder:
    """Stateful decoder for the BEAMBREAK_Module. Pairs each BLOCKED with
    its next CLEAR per gate and emits `gate_A_break_us` / `gate_B_break_us`
    with the duration in microseconds.

    Wire format (per BLE notification): 2 bytes packed `<BB`:
        gate_id (uint8, 1 or 2), state (uint8, 1=BLOCKED 0=CLEAR)

    The firmware no longer ships a timestamp, so we use Pi-side
    `time.monotonic()` at notification arrival. To suppress the resulting
    BLE-batching / sensor-switching noise, durations outside a plausible
    classroom range are dropped:

      < 5 ms   -> would imply >10 m/s with a 5 cm flag; almost certainly
                  a sensor flicker or two BLE notifications arriving in
                  the same packet.
      > 60 s   -> the matching CLEAR was probably missed; the next
                  BLOCKED reset would otherwise pair with stale state.
    """
    MIN_BREAK_US = 5_000
    MAX_BREAK_US = 60_000_000
    last_blocked_t: dict[int, float] = {}

    def decode(data: bytes):
        if len(data) != 2:
            return ()
        gate_id, state = struct.unpack("<BB", data)
        label = {1: "A", 2: "B"}.get(gate_id)
        if label is None:
            return ()
        now = time.monotonic()
        if state == 1:
            last_blocked_t[gate_id] = now
            return ()
        start = last_blocked_t.pop(gate_id, None)
        if start is None:
            return ()
        dur_us = (now - start) * 1_000_000.0
        if dur_us < MIN_BREAK_US or dur_us > MAX_BREAK_US:
            return ()
        return ((f"gate_{label}_break_us", dur_us),)

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
        name_prefix="BEAMBREAK_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        char_uuid="7c2b6f3a-4a8c-4d24-8f8b-32e2a5c76f10",
        decoder=_make_beambreak_decoder,
        description="Photogate: pairs BLOCKED/CLEAR into gate_A/B_break_us",
    ),
    "TOF_Module": Profile(
        name="TOF_Module",
        service_uuid="f30c13bf-c618-424d-aeb6-d035b933750f",
        char_uuid="9c4b7f8e-2b42-4d9a-9a26-6ab3a1d43f11",
        decoder=_stateless(_decode_tof_distance),
        description="VL53L0X distance sensor: distance_mm",
    ),
}


def _profile_id_for_name(advertised_name: str) -> str | None:
    """Return the PROFILES key whose name (or name_prefix) matches the
    advertised device name, or None if no profile matches."""
    if advertised_name in PROFILES:
        return advertised_name
    for pid, prof in PROFILES.items():
        if prof.name_prefix and advertised_name.startswith(prof.name_prefix):
            return pid
    return None


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
        # Diagnostic: log everything visible (named or not) so we can debug
        # cases where the OS BLE cache reports stale names.
        for addr, (dev, adv) in found.items():
            log.info("[BLE]   seen %s  name=%r  rssi=%s  uuids=%s",
                     addr, dev.name, adv.rssi, list(adv.service_uuids or []))
        for addr, (dev, adv) in found.items():
            name = dev.name or ""
            profile_id = _profile_id_for_name(name)
            if profile_id is None:
                # If we'd previously catalogued this address with a name it
                # no longer matches (e.g. the ESP32 was reflashed), drop the
                # stale entry so it doesn't keep showing up.
                stale = self._devices.get(addr)
                if stale is not None and not stale.connected and not stale.connecting:
                    if stale.name != name:
                        self._devices.pop(addr, None)
                continue
            existing = self._devices.get(addr)
            if existing:
                existing.rssi = adv.rssi
                existing.last_seen = now
                # Same address, different advertised name -> the device was
                # reflashed. Update the metadata so the UI shows the truth.
                if existing.name != name and not existing.connected:
                    existing.name = name
                    existing.profile_id = profile_id
                if not existing.connected:
                    existing.error = None
            else:
                self._devices[addr] = DeviceState(
                    address=addr, name=name, rssi=adv.rssi,
                    profile_id=profile_id, last_seen=now,
                )
        # Evict stale, idle devices so the list doesn't grow without bound.
        stale_cutoff = now - 60
        for addr in [a for a, d in self._devices.items()
                     if not d.connected and not d.connecting and d.last_seen < stale_cutoff]:
            self._devices.pop(addr, None)
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

    def forget_idle(self) -> int:
        """Drop all scanned, idle devices from the device list. Connected
        and connecting entries are preserved. Returns the count dropped."""
        before = len(self._devices)
        self._devices = {a: d for a, d in self._devices.items()
                         if d.connected or d.connecting}
        return before - len(self._devices)

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
                try:
                    await client.start_notify(char_uuid, on_notify)
                except Exception as e:
                    # Char UUID either isn't on this device or wasn't found by
                    # service discovery. Fall back to the first NOTIFY char.
                    log.warning(
                        "[BLE] %s: char %s not found (%s); auto-discovering",
                        d.name, char_uuid, e,
                    )
                    char_uuid = self._discover_notify_char(client)
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
