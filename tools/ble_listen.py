#!/usr/bin/env python3
"""Connect to a LABKickstart ESP32 over BLE and print events.

Use this from the Pi (or your Mac) to confirm an ESP32 is advertising,
connecting, and pushing notifications - before bothering with the full
server.

The script auto-discovers the first NOTIFY-able characteristic on the
device, so it works for both module families:
  - Photogate test module          (LK-Photogate-A, JSON events)
  - IMU module v1/v2               (IMU_Module, packed 5-float struct)

Examples
--------
Just scan and print everything in range:

    python tools/ble_listen.py --scan

Connect to the IMU module and stream:

    python tools/ble_listen.py                       # default: IMU_Module
    python tools/ble_listen.py --name LK-Photogate-A
    python tools/ble_listen.py --name IMU_Module --decode imu

Requires:
    pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
except ImportError:
    sys.stderr.write("error: bleak is not installed. run: pip install bleak\n")
    sys.exit(1)

DEFAULT_NAME = "IMU_Module"
DEFAULT_NAME_PREFIX = ""  # show everything by default; IMU sketch doesn't use the LK- prefix


# ---------- Decoders ----------

def _decode_json(data: bytes) -> str | None:
    text = data.decode("utf-8", errors="replace").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    channel = obj.get("channel", "?")
    value = obj.get("value")
    extras = {k: v for k, v in obj.items() if k not in ("channel", "value")}
    extra = ("  " + " ".join(f"{k}={v}" for k, v in extras.items())) if extras else ""
    return f"{channel}={value}{extra}"


def _decode_imu(data: bytes) -> str | None:
    """Decode the IMU module's 5-float little-endian packed struct."""
    if len(data) != 20:
        return None
    pitch, roll, ax, ay, az = struct.unpack("<5f", data)
    return (f"pitch={pitch:7.2f}deg  roll={roll:7.2f}deg  "
            f"a=({ax:6.2f}, {ay:6.2f}, {az:6.2f}) m/s^2")


def _decode_hex(data: bytes) -> str:
    return f"raw[{len(data)}b]={data.hex()}"


DECODERS = {
    "auto": [_decode_json, _decode_imu, _decode_hex],
    "json": [_decode_json, _decode_hex],
    "imu":  [_decode_imu, _decode_hex],
    "hex":  [_decode_hex],
}


# ---------- Scan / connect ----------

async def scan(timeout: float, prefix: str) -> list[BLEDevice]:
    print(f"scanning for {timeout:.1f}s (prefix={prefix!r})...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    matches = [
        (dev, adv) for (dev, adv) in found.values()
        if (dev.name or "").startswith(prefix)
    ]
    if not matches:
        print("  (none found)")
        return []
    for dev, adv in matches:
        print(f"  {dev.address}  {dev.name or '(no name)':24s}  rssi={adv.rssi}")
    return [dev for dev, _ in matches]


async def find_one(name: str, timeout: float) -> Optional[BLEDevice]:
    print(f"looking for {name!r} (up to {timeout:.0f}s)...")
    return await BleakScanner.find_device_by_filter(
        lambda d, _: (d.name or "") == name, timeout=timeout
    )


def _pick_notify_char(client: BleakClient, override_uuid: str | None):
    """Pick a characteristic to subscribe to.

    Preference order:
      1. an explicit --char UUID (errors if not present / not notifiable)
      2. the first characteristic with NOTIFY in any service
    """
    services = client.services
    if override_uuid:
        for svc in services:
            for ch in svc.characteristics:
                if ch.uuid.lower() == override_uuid.lower():
                    if "notify" not in ch.properties:
                        raise RuntimeError(f"{override_uuid} is not NOTIFY-capable")
                    return ch
        raise RuntimeError(f"characteristic {override_uuid} not found on device")
    for svc in services:
        for ch in svc.characteristics:
            if "notify" in ch.properties:
                return ch
    raise RuntimeError("no NOTIFY characteristics on this device")


async def stream(device: BLEDevice, char_uuid: str | None, decode_mode: str) -> None:
    decoders = DECODERS[decode_mode]
    n_events = 0
    started = time.monotonic()

    def handle(_, data: bytearray) -> None:
        nonlocal n_events
        n_events += 1
        wall = time.strftime("%H:%M:%S")
        b = bytes(data)
        for d in decoders:
            line = d(b)
            if line is not None:
                print(f"[{wall}] #{n_events:<4} {line}")
                return
        print(f"[{wall}] #{n_events:<4} {_decode_hex(b)}")  # last-resort

    print(f"connecting to {device.address} ({device.name})...")
    async with BleakClient(device) as client:
        if not client.is_connected:
            print("  failed to connect")
            return

        try:
            ch = _pick_notify_char(client, char_uuid)
        except RuntimeError as e:
            print(f"  {e}")
            print("  characteristics found:")
            for svc in client.services:
                for c in svc.characteristics:
                    print(f"    {c.uuid}  props={','.join(c.properties)}")
            return

        print(f"  connected. subscribing to {ch.uuid} ({decode_mode} decode)...")
        await client.start_notify(ch.uuid, handle)
        print("  streaming. press Ctrl-C to stop.\n")
        try:
            while client.is_connected:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await client.stop_notify(ch.uuid)
            except Exception:
                pass
            elapsed = time.monotonic() - started
            if elapsed > 0:
                print(f"\nstopped. {n_events} events in {elapsed:.1f}s "
                      f"({n_events / elapsed:.2f}/s)")
            else:
                print(f"\nstopped. {n_events} events.")


async def main_async(args: argparse.Namespace) -> int:
    if args.scan:
        await scan(args.timeout, args.prefix)
        return 0

    device = await find_one(args.name, args.timeout)
    if device is None:
        print(f"could not find {args.name!r}. is the ESP32 powered on and in range?")
        print("try `--scan` to list devices.")
        return 1
    await stream(device, args.char, args.decode)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", default=DEFAULT_NAME,
                   help=f"BLE device name to connect to (default: {DEFAULT_NAME})")
    p.add_argument("--scan", action="store_true",
                   help="scan only; don't connect")
    p.add_argument("--prefix", default=DEFAULT_NAME_PREFIX,
                   help="name prefix filter for --scan (default: empty = all)")
    p.add_argument("--char", default=None,
                   help="characteristic UUID to subscribe to (default: first NOTIFY found)")
    p.add_argument("--decode", choices=list(DECODERS.keys()), default="auto",
                   help="payload decoder: auto|json|imu|hex (default: auto)")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="seconds to scan when finding the device (default: 8)")
    args = p.parse_args()

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
