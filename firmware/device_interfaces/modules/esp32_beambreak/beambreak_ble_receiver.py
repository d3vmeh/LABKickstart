import asyncio
import struct
import csv
import time
from datetime import datetime

from bleak import BleakScanner, BleakClient

DEVICE_NAME = "BEAMBREAK_Module"
SERVICE_UUID = "f30c13bf-c618-424d-aeb6-d035b933750f"
BEAMBREAK_UUID = "7c2b6f3a-4a8c-4d24-8f8b-32e2a5c76f10"

CSV_FILE = "beambreak_log.csv"


last_blocked_time_us = None
last_gate_id = None


def decode_beambreak_packet(data: bytearray):
    """
    DESP32 binary struct format:
        struct BeamBreakData {
            uint8_t gate_id;       // 1 or 2
            uint8_t state;         // 1 = BLOCKED, 0 = CLEAR
            uint32_t timestamp_us; // micros()
        };

    Total = 1 + 1 + 4 = 6 bytes
    Python unpack: <BBI
    
    """
    raw = bytes(data)

    if len(raw) == 6:
        gate_id, state, timestamp_us = struct.unpack("<BBI", raw)
        return {
            "gate_id": gate_id,
            "state": "BLOCKED" if state == 1 else "CLEAR",
            "state_raw": state,
            "timestamp_us": timestamp_us,
            "raw_format": "binary_<BBI>",
            "raw_hex": raw.hex(),
        }


    try:
        text = raw.decode("utf-8").strip()
        if text:
            parts = [p.strip() for p in text.split(",")]

            if len(parts) == 3:
                gate_id = int(parts[0])
                state = parts[1].upper()
                timestamp_us = int(parts[2])
                return {
                    "gate_id": gate_id,
                    "state": state,
                    "state_raw": 1 if state == "BLOCKED" else 0,
                    "timestamp_us": timestamp_us,
                    "raw_format": "utf8_gate_state_timestamp",
                    "raw_hex": raw.hex(),
                }

            if len(parts) == 1:
                state = parts[0].upper()
                return {
                    "gate_id": None,
                    "state": state,
                    "state_raw": 1 if state == "BLOCKED" else 0,
                    "timestamp_us": None,
                    "raw_format": "utf8_state_only",
                    "raw_hex": raw.hex(),
                }

    except Exception:
        pass

  
    if len(raw) == 1:
        state_raw = struct.unpack("<B", raw)[0]
        return {
            "gate_id": None,
            "state": "BLOCKED" if state_raw == 1 else "CLEAR",
            "state_raw": state_raw,
            "timestamp_us": None,
            "raw_format": "uint8_state",
            "raw_hex": raw.hex(),
        }

  
    if len(raw) == 4:
        timestamp_us = struct.unpack("<I", raw)[0]
        return {
            "gate_id": None,
            "state": "TRIGGER",
            "state_raw": None,
            "timestamp_us": timestamp_us,
            "raw_format": "uint32_timestamp_us",
            "raw_hex": raw.hex(),
        }

    return {
        "gate_id": None,
        "state": "UNKNOWN",
        "state_raw": None,
        "timestamp_us": None,
        "raw_format": f"unknown_{len(raw)}_bytes",
        "raw_hex": raw.hex(),
    }


def process_timing(decoded):
    global last_blocked_time_us, last_gate_id

    gate_id = decoded["gate_id"]
    state = decoded["state"]
    timestamp_us = decoded["timestamp_us"]

    delta_s = None

    if timestamp_us is None:
        return None

    if state == "BLOCKED" or state == "TRIGGER":
        if last_blocked_time_us is not None:
            delta_us = timestamp_us - last_blocked_time_us

            # Handle micros() overflow roughly, ESP32 micros overflows after about 71 minutes
            if delta_us < 0:
                delta_us += 2**32

            delta_s = delta_us / 1_000_000.0

        last_blocked_time_us = timestamp_us
        last_gate_id = gate_id

    return delta_s


def make_notification_handler(csv_writer, csv_file):
    def handle_notification(sender, data):
        timestamp_pi = time.time()
        readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        decoded = decode_beambreak_packet(data)
        delta_s = process_timing(decoded)

        gate_id = decoded["gate_id"]
        state = decoded["state"]
        timestamp_us = decoded["timestamp_us"]
        raw_format = decoded["raw_format"]
        raw_hex = decoded["raw_hex"]

        gate_text = f"gate={gate_id}" if gate_id is not None else "gate=?"
        esp_time_text = f"esp_time={timestamp_us} us" if timestamp_us is not None else "esp_time=?"

        if delta_s is not None:
            print(
                f"[{readable_time}] {gate_text}, state={state}, "
                f"{esp_time_text}, delta={delta_s:.6f} s"
            )
        else:
            print(
                f"[{readable_time}] {gate_text}, state={state}, "
                f"{esp_time_text}, format={raw_format}"
            )

        csv_writer.writerow([
            timestamp_pi,
            readable_time,
            gate_id,
            state,
            timestamp_us,
            delta_s,
            raw_format,
            raw_hex,
        ])
        csv_file.flush()

    return handle_notification


async def find_beambreak_device():
    print(f"Scanning for BLE device named '{DEVICE_NAME}'...")

    devices = await BleakScanner.discover(timeout=15.0)

    print("\nNearby BLE devices:")
    for device in devices:
        print(f"  {device.address}  name={device.name}")

    for device in devices:
        if device.name == DEVICE_NAME:
            print(f"\nFound {DEVICE_NAME}: {device.address}")
            return device

    print(f"\nCould not find device named '{DEVICE_NAME}'.")
    return None


async def main():
    device = await find_beambreak_device()

    if device is None:
        print("\nTroubleshooting:")
        print("1. Make sure the ESP32 beam break module is powered on.")
        print("2. Make sure BLE advertising has started.")
        print("3. Make sure no phone/laptop is already connected to the ESP32 over BLE.")
        print("4. Check whether the BLE device name is really 'BEAMBREAK_Module'.")
        return

    print(f"\nConnecting to {device.name} at {device.address}...")

    async with BleakClient(device.address) as client:
        print("Connected:", client.is_connected)

        print("\nServices and characteristics:")
        for service in client.services:
            print(f"[Service] {service.uuid}")
            for char in service.characteristics:
                print(f"  [Char] {char.uuid}  properties={char.properties}")

        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)

            if f.tell() == 0:
                writer.writerow([
                    "pi_timestamp",
                    "readable_time",
                    "gate_id",
                    "state",
                    "esp_timestamp_us",
                    "delta_s",
                    "raw_format",
                    "raw_hex",
                ])

            handler = make_notification_handler(writer, f)

            print("\nSubscribing to beam break characteristic:")
            print(BEAMBREAK_UUID)

            await client.start_notify(BEAMBREAK_UUID, handler)

            print("\nListening for beam break events. Press Ctrl+C to stop.\n")

            while True:
                await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
