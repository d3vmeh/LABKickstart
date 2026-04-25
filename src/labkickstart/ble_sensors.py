"""Real-hardware BLE sensor adapters that plug into the SensorSource
protocol used elsewhere in the codebase.

Behavior is "scan-connect-stream-reconnect-on-failure" so the same loop
keeps running through ESP32 resets, range drops, etc. Channel names
match the mocks one-for-one, so kits and the UI need no changes when
swapping mock for real.

Lazy bleak import: the `bleak` library only loads when this module is
imported, so the rest of the app still runs on machines without it.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import AsyncIterator

from .sensors import DeviceInfo, Sample

log = logging.getLogger(__name__)


class BLEIMUSensor:
    """Connects to the teammate's `IMU_Module` ESP32 and yields five
    Sample channels per BLE notification: pitch_deg, roll_deg, accel_x,
    accel_y, accel_z.

    The wire protocol (UUIDs, packed 5-float struct) is fixed by the
    firmware in firmware/device_interfaces/modules/esp32_IMU_module_transmitter.
    """

    DEVICE_NAME = "IMU_Module"
    SERVICE_UUID = "f30c13bf-c618-424d-aeb6-d035b933750f"
    IMU_DATA_UUID = "2be54bb2-4e7d-4ac2-885d-c019bc130fea"

    SCAN_TIMEOUT_S = 10.0
    RETRY_BACKOFF_S = 2.0
    DATA_TIMEOUT_S = 3.0     # per-frame wait; just loops, doesn't disconnect

    def __init__(self, device_id: str = "imu-ble-01", name: str = "IMU_Module"):
        self._info = DeviceInfo(device_id=device_id, name=name, rssi=None, connected=False)

    def devices(self) -> list[DeviceInfo]:
        return [self._info]

    async def stream(self) -> AsyncIterator[Sample]:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as e:
            raise RuntimeError(
                "bleak is not installed - run `pip install -r requirements.txt`"
            ) from e

        start = time.monotonic()
        # Bounded queue: BLE callback puts here; stream consumer yields.
        queue: asyncio.Queue[Sample] = asyncio.Queue(maxsize=2000)

        def make_handler():
            def handler(_sender, data: bytearray):
                b = bytes(data)
                if len(b) != 20:
                    log.debug("dropping unexpected payload size %d", len(b))
                    return
                try:
                    pitch, roll, ax, ay, az = struct.unpack("<5f", b)
                except struct.error as e:
                    log.warning("struct decode failed: %s", e)
                    return
                t = time.monotonic() - start
                for channel, value in (
                    ("pitch_deg", pitch),
                    ("roll_deg", roll),
                    ("accel_x", ax),
                    ("accel_y", ay),
                    ("accel_z", az),
                ):
                    try:
                        queue.put_nowait(Sample(self._info.device_id, t, channel, value))
                    except asyncio.QueueFull:
                        # Slow consumer; drop oldest by replacing the queue is overkill.
                        # Just drop the newest sample so we don't block the BLE thread.
                        pass
            return handler

        while True:
            try:
                log.info("[BLE] scanning for %r (up to %.0fs)",
                         self.DEVICE_NAME, self.SCAN_TIMEOUT_S)
                dev = await BleakScanner.find_device_by_filter(
                    lambda d, _adv: (d.name or "") == self.DEVICE_NAME,
                    timeout=self.SCAN_TIMEOUT_S,
                )
                if dev is None:
                    log.info("[BLE] %r not found; retrying in %.0fs",
                             self.DEVICE_NAME, self.RETRY_BACKOFF_S)
                    await asyncio.sleep(self.RETRY_BACKOFF_S)
                    continue

                log.info("[BLE] connecting to %s", dev.address)
                async with BleakClient(dev) as client:
                    if not client.is_connected:
                        log.warning("[BLE] connect returned but is_connected=False")
                        await asyncio.sleep(self.RETRY_BACKOFF_S)
                        continue

                    await client.start_notify(self.IMU_DATA_UUID, make_handler())
                    self._info.connected = True
                    log.info("[BLE] connected; streaming notifications")

                    while client.is_connected:
                        try:
                            sample = await asyncio.wait_for(
                                queue.get(), timeout=self.DATA_TIMEOUT_S
                            )
                            yield sample
                        except asyncio.TimeoutError:
                            # No notifications for a while but still connected.
                            # Loop and keep waiting.
                            log.debug("[BLE] %.0fs without data", self.DATA_TIMEOUT_S)
                            continue

                    log.info("[BLE] disconnected; will reconnect")
            except asyncio.CancelledError:
                # Server is shutting down; let the cancellation propagate.
                raise
            except Exception as e:
                log.warning("[BLE] error: %s; backing off %.1fs",
                            e, self.RETRY_BACKOFF_S)
                await asyncio.sleep(self.RETRY_BACKOFF_S)
            finally:
                self._info.connected = False
