/*  ESP32 IMU BLE transmitter - v2
 *
 *  Patched copy of esp32_IMU_module_transmitter.ino. Same wire protocol
 *  (device name, service UUID, characteristic UUID, packed 5-float struct
 *  payload) so any client written against the original keeps working.
 *
 *  Changes from v1:
 *    - BLEServerCallbacks: re-starts advertising on disconnect, so the Pi
 *      can reconnect without a hardware reset of the ESP32.
 *    - Adds the service UUID to the advertising packet, so service-UUID
 *      scanners discover the module (the teammate's v1 advertised by name
 *      only).
 *    - Calls Serial.begin so the "No accel detected" message actually
 *      prints if the LSM303 isn't on I2C.
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include "stdint.h"

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_Accel.h>

#define BLE_DELAY 20    // ms between notifications -> 50 Hz

using Precision = float;

Adafruit_LSM303_Accel_Unified accel = Adafruit_LSM303_Accel_Unified(54321);

#define SERVICE_UUID            "f30c13bf-c618-424d-aeb6-d035b933750f"
#define IMU_DATA_UUID           "2be54bb2-4e7d-4ac2-885d-c019bc130fea"

BLECharacteristic* pIMUCharacteristic = nullptr;
BLEAdvertising*    pAdvertising       = nullptr;
volatile bool      deviceConnected    = false;

struct __attribute__((packed)) IMUData {
  Precision pitch;
  Precision roll;
  Precision accelX;
  Precision accelY;
  Precision accelZ;
} imu_data;

// ---------- BLE callbacks ----------
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    deviceConnected = true;
    Serial.println("[BLE] central connected");
  }
  void onDisconnect(BLEServer*) override {
    deviceConnected = false;
    Serial.println("[BLE] central disconnected, re-advertising");
    // Without this the module goes silent until you press RESET.
    BLEDevice::startAdvertising();
  }
};

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("[boot] IMU_Module v2");

  if (!accel.begin()) {
    Serial.println("[boot] No accel detected - check wiring (SDA/SCL/3V3/GND)");
    while (1) { delay(1000); }
  }

  BLEDevice::init("IMU_Module");
  BLEServer* pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService* pService = pServer->createService(SERVICE_UUID);

  pIMUCharacteristic = pService->createCharacteristic(
      IMU_DATA_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  pIMUCharacteristic->addDescriptor(new BLE2902());

  pService->start();

  pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);   // makes service-UUID scanners find us
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);          // helps iOS/macOS pair quickly
  BLEDevice::startAdvertising();

  Serial.println("[BLE] advertising as IMU_Module");
}

void loop() {
  sensors_event_t event;
  accel.getEvent(&event);

  imu_data.accelX = event.acceleration.x;
  imu_data.accelY = event.acceleration.y;
  imu_data.accelZ = event.acceleration.z;

  imu_data.pitch = atan2(-imu_data.accelX,
                         sqrt(imu_data.accelY * imu_data.accelY +
                              imu_data.accelZ * imu_data.accelZ)) * SENSORS_RADS_TO_DPS;
  imu_data.roll  = atan2(imu_data.accelY, imu_data.accelZ) * SENSORS_RADS_TO_DPS;

  if (deviceConnected && pIMUCharacteristic) {
    pIMUCharacteristic->setValue((uint8_t*) &imu_data, sizeof(IMUData));
    pIMUCharacteristic->notify();
  }

  delay(BLE_DELAY);
}
