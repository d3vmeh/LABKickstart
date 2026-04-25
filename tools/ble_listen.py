#!/usr/bin/env python3
"""Connect to a LABKickstart ESP32 over BLE and print events.

Use this from the Pi (or your Mac) to confirm an ESP32 is advertising,
connecting, and pushing notifications - before bothering with the full
server.

Examples
--------
Just scan for LK-* devices and print what you see:

    python tools/ble_listen.py --scan

Connect to gate A and stream events until Ctrl-C:

    python tools/ble_listen.py

Connect to a specific device name:

    python tools/ble_listen.py --name LK-Photogate-A

Requires:
    pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
except ImportError:
    sys.stderr.write("error: bleak is not installed. run: pip install bleak\n")
    sys.exit(1)

# Must match firmware/photogate_test/photogate_test.ino
SERVICE_UUID = "5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f"
EVENTS_CHAR_UUID = "5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f"

DEFAULT_NAME = "LK-Photogate-A"
DEFAULT_NAME_PREFIX = "LK-"


async def scan(timeout: float, prefix: str) -> list[BLEDevice]:
    print(f"scanning for {timeout:.1f}s (prefix={prefix!r})...")
    devices = await BleakScanner.discover(timeout=timeout)
    matches = [d for d in devices if (d.name or "").startswith(prefix)]
    if not matches:
        print("  (none found)")
        return []
    for d in matches:
        print(f"  {d.address}  {d.name}  rssi={d.rssi}")
    return matches


async def find_one(name: str, timeout: float) -> Optional[BLEDevice]:
    print(f"looking for {name!r} (up to {timeout:.0f}s)...")
    return await BleakScanner.find_device_by_filter(
        lambda d, _: (d.name or "") == name, timeout=timeout
    )


async def stream(device: BLEDevice) -> None:
    n_events = 0
    started = time.monotonic()

    def handle(_, data: bytearray) -> None:
        nonlocal n_events
        n_events += 1
        text = bytes(data).decode("utf-8", errors="replace").strip()
        wall = time.strftime("%H:%M:%S")
        try:
            obj = json.loads(text)
            gate = obj.get("gate", "?")
            us = obj.get("break_us")
            print(f"[{wall}] #{n_events:<4} gate={gate} break={us} us  raw={text}")
        except json.JSONDecodeError:
            print(f"[{wall}] #{n_events:<4} non-json: {text!r}")

    print(f"connecting to {device.address} ({device.name})...")
    async with BleakClient(device) as client:
        if not client.is_connected:
            print("  failed to connect")
            return
        print("  connected. subscribing to events...")
        await client.start_notify(EVENTS_CHAR_UUID, handle)
        print("  streaming. press Ctrl-C to stop.\n")
        try:
            while client.is_connected:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await client.stop_notify(EVENTS_CHAR_UUID)
            except Exception:
                pass
            elapsed = time.monotonic() - started
            print(f"\nstopped. {n_events} events in {elapsed:.1f}s "
                  f"({n_events / elapsed:.2f}/s)" if elapsed > 0 else f"\nstopped. {n_events} events.")


async def main_async(args: argparse.Namespace) -> int:
    if args.scan:
        await scan(args.timeout, args.prefix)
        return 0

    device = await find_one(args.name, args.timeout)
    if device is None:
        print(f"could not find {args.name!r}. is the ESP32 powered on and in range?")
        print("try `--scan` to list LK-* devices.")
        return 1
    await stream(device)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", default=DEFAULT_NAME,
                   help=f"BLE device name to connect to (default: {DEFAULT_NAME})")
    p.add_argument("--scan", action="store_true",
                   help="scan only; don't connect")
    p.add_argument("--prefix", default=DEFAULT_NAME_PREFIX,
                   help=f"name prefix used during --scan (default: {DEFAULT_NAME_PREFIX})")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="seconds to scan when finding the device (default: 8)")
    args = p.parse_args()

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
