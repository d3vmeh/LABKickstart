import asyncio
import struct
import csv
import time
from datetime import datetime

from bleak import BleakScanner, BleakClient
DEVICE_NAME = "TOF_Module"
SERVICE_UUID = "f30c13bf-c618-424d-aeb6-d035b933750f"
TOF_DISTANCE_UUID = "PUT_YOUR_TOF_DISTANCE_UUID_HERE"

CSV_FILE = "tof_distance_log.csv"


def decode_distance_packet(data: bytearray):
    """
    Decode distance data sent by ESP32.

    This supports several common formats:
    1. float32, little-endian, 4 bytes
       Example ESP32:
       float distance_mm;
       characteristic->setValue((uint8_t*)&distance_mm, sizeof(distance_mm));

    2. uint16, little-endian, 2 bytes
       Example ESP32:
       uint16_t distance_mm;
       characteristic->setValue((uint8_t*)&distance_mm, sizeof(distance_mm));

    3. uint32, little-endian, 4 bytes
       Example ESP32:
       uint32_t distance_mm;

    4. UTF-8 string
       Example ESP32:
       characteristic->setValue(String(distance_mm).c_str());
    """
    raw = bytes(data)

    # Case 1: Try UTF-8 string first, e.g. b"123.45"
    try:
        text = raw.decode("utf-8").strip()
        if text:
            value = float(text)
            return {
                "distance": value,
                "unit": "unknown/string",
                "raw_format": "utf8_string",
                "raw_hex": raw.hex(),
            }
    except Exception:
        pass

    # Case 2: 2-byte uint16, often used for distance in mm
    if len(raw) == 2:
        value = struct.unpack("<H", raw)[0]
        return {
            "distance": value,
            "unit": "mm",
            "raw_format": "uint16",
            "raw_hex": raw.hex(),
        }

    # Case 3: 4-byte float32
    if len(raw) == 4:
        float_value = struct.unpack("<f", raw)[0]
        uint32_value = struct.unpack("<I", raw)[0]

        # Heuristic:
        # If float looks physically reasonable, use float.
        # Otherwise, fall back to uint32.
        if -1000.0 < float_value < 10000.0:
            return {
                "distance": float_value,
                "unit": "unknown/float32",
                "raw_format": "float32",
                "raw_hex": raw.hex(),
            }

        return {
            "distance": uint32_value,
            "unit": "mm",
            "raw_format": "uint32",
            "raw_hex": raw.hex(),
        }

    # Case 4: Unknown format
    return {
        "distance": None,
        "unit": "unknown",
        "raw_format": f"{len(raw)} bytes",
        "raw_hex": raw.hex(),
    }


def make_notification_handler(csv_writer, csv_file):
    def handle_notification(sender, data):
        timestamp = time.time()
        readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        decoded = decode_distance_packet(data)

        distance = decoded["distance"]
        unit = decoded["unit"]
        raw_format = decoded["raw_format"]
        raw_hex = decoded["raw_hex"]

        if distance is not None:
            print(
                f"[{readable_time}] "
                f"distance={distance:.3f} {unit}, "
                f"format={raw_format}"
            )
        else:
            print(
                f"[{readable_time}] "
                f"Could not decode packet. "
                f"format={raw_format}, raw={raw_hex}"
            )

        csv_writer.writerow([
            timestamp,
            readable_time,
            distance,
            unit,
            raw_format,
            raw_hex,
        ])
        csv_file.flush()

    return handle_notification


async def find_tof_device():
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
    device = await find_tof_device()

    if device is None:
        print("\nTroubleshooting:")
        print("1. Make sure the ESP32 ToF module is powered on.")
        print("2. Make sure BLE advertising has started.")
        print("3. Make sure no phone/laptop is already connected to the ESP32 over BLE.")
        print("4. Check whether the BLE device name is really 'TOF_Module'.")
        return

    print(f"\nConnecting to {device.name} at {device.address}...")

    async with BleakClient(device.address) as client:
        print("Connected:", client.is_connected)

        print("\nServices and characteristics:")
        for service in client.services:
            print(f"[Service] {service.uuid}")
            for char in service.characteristics:
                print(f"  [Char] {char.uuid}  properties={char.properties}")

        if TOF_DISTANCE_UUID == "PUT_YOUR_TOF_DISTANCE_UUID_HERE":
            print("\nERROR: You must replace TOF_DISTANCE_UUID with the actual ESP32 characteristic UUID.")
            return

        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)

            if f.tell() == 0:
                writer.writerow([
                    "timestamp",
                    "readable_time",
                    "distance",
                    "unit",
                    "raw_format",
                    "raw_hex",
                ])

            handler = make_notification_handler(writer, f)

            print("\nSubscribing to ToF distance characteristic:")
            print(TOF_DISTANCE_UUID)

            await client.start_notify(TOF_DISTANCE_UUID, handler)

            print("\nListening for ToF distance data. Press Ctrl+C to stop.\n")

            while True:
                await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
