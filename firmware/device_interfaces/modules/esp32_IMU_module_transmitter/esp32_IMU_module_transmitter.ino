/*  this is code for esp32 IMU BLE transmitter module */

/*  for BLE transmission */
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include "stdint.h"

/*  for IMU data  */
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_Accel.h>

// constants
#define BLE_DELAY 100    // in ms

// if we want to change between double and float values
using Precision = float;

Adafruit_LSM303_Accel_Unified accel = Adafruit_LSM303_Accel_Unified(54321);

/*  add more UUID for more information  */
#define SERVICE_UUID            "f30c13bf-c618-424d-aeb6-d035b933750f"
#define IMU_DATA_UUID           "2be54bb2-4e7d-4ac2-885d-c019bc130fea"

BLECharacteristic* pIMUCharacteristic;

// want to sent a whole packet with information 
// to later be unpacked by the Pi
struct __attribute__((packed)) IMUData {
  Precision pitch;
  Precision roll;
  Precision accelX;
  Precision accelY;
  Precision accelZ;
} imu_data;


// v2: re-start advertising on disconnect so the Pi can reconnect
// without resetting the ESP32.
class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer*) override {
    BLEDevice::startAdvertising();
  }
};

void setup() {
  if (!accel.begin()) {
    Serial.println("No accel detected");
    while (1);
  }

  BLEDevice::init("IMU_Module");
  BLEServer* pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());        
  BLEService* pService = pServer->createService(SERVICE_UUID);

  pIMUCharacteristic = pService->createCharacteristic(IMU_DATA_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pIMUCharacteristic->addDescriptor(new BLE2902());
  
  pService->start();
  // broadcast 
  pServer->getAdvertising()->start();
}

void loop() {
  sensors_event_t event;
  accel.getEvent(&event);

  imu_data.accelX = event.acceleration.x;
  imu_data.accelY = event.acceleration.y;
  imu_data.accelZ = event.acceleration.z;

  imu_data.pitch = atan2(-imu_data.accelX, sqrt(imu_data.accelY * imu_data.accelY + imu_data.accelZ * imu_data.accelZ)) * SENSORS_RADS_TO_DPS;
  
  imu_data.roll = atan2(imu_data.accelY, imu_data.accelZ) * SENSORS_RADS_TO_DPS;

  pIMUCharacteristic->setValue((uint8_t*) &imu_data, sizeof(IMUData));
  pIMUCharacteristic->notify();

  delay(BLE_DELAY);
}

