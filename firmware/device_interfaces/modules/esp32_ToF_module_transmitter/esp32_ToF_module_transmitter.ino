#include <Wire.h>

/*  for BLE tranmission   */
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include "stdint.h"

// include the right library, just standard VL6180X
#include "VL6180X.h"

#define SERVICE_UUID        "f30c13bf-c618-424d-aeb6-d035b933750f"
#define TOF_DISTANCE_UUID   "9c4b7f8e-2b42-4d9a-9a26-6ab3a1d43f11"

#define BLE_DEVICE_NAME     "TOF_Module"

BLECharacteristic* pDistanceCharacteristic;

using Precision = float;

VL6180X tof;

#define SCALE_FACTOR 2
#define SEND_DELAY_MS 50

struct __attribute__((packed)) ToFData {
  Precision distance_mm;       // distance in millimeters
  uint8_t status;          // 0 = valid, 1 = out of range / invalid
};

ToFData tof_data;

// important; so it reconnects after a disconnection
class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer*) override {
    BLEDevice::startAdvertising();
  }
};

void setup() {
  Serial.begin(115200);
  Serial.println();

  // Start I2C
  Wire.begin();

  // Start ToF sensor
  tof.init();
  tof.configureDefault();
  tof.setScaling(SCALE_FACTOR);
  tof.setTimeout(500);

  // Start BLE
  BLEDevice::init(BLE_DEVICE_NAME);

  BLEServer* pServer = BLEDevice::createServer();

  // important for reconnecting
  pServer->setCallbacks(new ServerCallbacks());        
  BLEService* pService = pServer->createService(SERVICE_UUID);

  pDistanceCharacteristic = pService->createCharacteristic(
    TOF_DISTANCE_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );

  pDistanceCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  pServer->getAdvertising()->start();

  // unnecessary, TODO: remove later
  Serial.print("BLE advertising started as: ");
  Serial.println(BLE_DEVICE_NAME);
  Serial.print("Distance characteristic UUID: ");
  Serial.println(TOF_DISTANCE_UUID);
}

void loop() {
  Precision distance = tof.readRangeSingleMillimeters();

  // check range status 
  uint8_t status = tof.readRangeStatus();

  if (status == 0) {
    // this is a valid reading
    tof_data.distance_mm = distance;
    tof_data.status = 0;
  } else {
    tof_data.distance_mm = -1;
    tof_data.status = 1;
  }

  pDistanceCharacteristic->setValue((uint8_t*)&tof_data, sizeof(ToFData));
  pDistanceCharacteristic->notify();

  // print statements for debugging 
  // remove later probably
  Serial.print("distance_mm=");
  Serial.print(tof_data.distance_mm);
  Serial.print(", status=");
  Serial.println(tof_data.status);

  delay(SEND_DELAY_MS);
}
