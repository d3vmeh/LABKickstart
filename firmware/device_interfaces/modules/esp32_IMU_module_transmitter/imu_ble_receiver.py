import asyncio
import struct
import csv
import time
from datetime import datetime

from bleak import BleakScanner, BleakClient


DEVICE_NAME = "IMU_Module"

SERVICE_UUID = "f30c13bf-c618-424d-aeb6-d035b933750f"
IMU_DATA_UUID = "2be54bb2-4e7d-4ac2-885d-c019bc130fea"

CSV_FILE = "imu_data_log.csv"


def decode_imu_packet(data: bytearray):
    raw = bytes(data)

    if len(raw) != 20:
        raise ValueError(f"Expected 20 bytes, got {len(raw)} bytes: {raw.hex()}")

    pitch, roll, accel_x, accel_y, accel_z = struct.unpack("<5f", raw)

    return {
        "pitch": pitch,
        "roll": roll,
        "accel_x": accel_x,
        "accel_y": accel_y,
        "accel_z": accel_z,
    }


def make_notification_handler(csv_writer, csv_file):
    def handle_notification(sender, data):
        try:
            imu = decode_imu_packet(data)
            timestamp = time.time()
            readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            print(
                f"[{readable_time}] "
                f"pitch={imu['pitch']:.2f} deg, "
                f"roll={imu['roll']:.2f} deg, "
                f"ax={imu['accel_x']:.3f}, "
                f"ay={imu['accel_y']:.3f}, "
                f"az={imu['accel_z']:.3f}"
            )

            csv_writer.writerow([
                timestamp,
                readable_time,
                imu["pitch"],
                imu["roll"],
                imu["accel_x"],
                imu["accel_y"],
                imu["accel_z"],
            ])
            csv_file.flush()

        except Exception as e:
            print(f"Failed to decode notification from {sender}: {e}")

    return handle_notification


async def find_imu_device():
    print(f"Scanning for BLE device named '{DEVICE_NAME}'...")

    devices = await BleakScanner.discover(timeout=10.0)

    print("\nNearby BLE devices:")
    for device in devices:
        print(f"  {device.address}  name={device.name}")

    for device in devices:
        if device.name == DEVICE_NAME:
            print(f"\nFound {DEVICE_NAME}: {device.address}")
            return device

    return None


async def main():
    device = await find_imu_device()

    if device is None:
        print(f"\nCould not find BLE device named '{DEVICE_NAME}'.")
        print("Check that the ESP32 is powered on, BLE advertising is started, and no other device is connected.")
        return

    print(f"\nConnecting to {device.name} at {device.address}...")

    async with BleakClient(device.address) as client:
        print("Connected:", client.is_connected)

        print("\nServices and characteristics:")
        services = client.services
        for service in services:
            print(f"[Service] {service.uuid}")
            for char in service.characteristics:
                print(f"  [Char] {char.uuid}  properties={char.properties}")

        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)

            if f.tell() == 0:
                writer.writerow([
                    "timestamp",
                    "readable_time",
                    "pitch_deg",
                    "roll_deg",
                    "accel_x",
                    "accel_y",
                    "accel_z",
                ])

            handler = make_notification_handler(writer, f)

            print(f"\nSubscribing to IMU characteristic:")
            print(IMU_DATA_UUID)

            await client.start_notify(IMU_DATA_UUID, handler)

            print("\nListening for IMU data. Press Ctrl+C to stop.\n")

            while True:
                await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
