#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include "stdint.h"

/*  add more UUID for more information  */
#define SERVICE_UUID            "f30c13bf-c618-424d-aeb6-d035b933750f"
#define PITCH_DEGREE_UUID       "e5547158-36a4-4c5b-94fb-9949913c56f4"

BLECharacteristic* pPitchCharacteristic;


void setup() {
  BLEDevice::init("LAB_QuickStart");
  BLEServer* pServer = BLEDevice::createServer();
  BLEService* pService = pServer->createService(SERVICE_UUID);

  // pitch degree characteristic
  pPitchCharacteristic = pService->createCharacteristic(PITCH_DEGREE_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pPitchCharacteristic->addDescriptor(new BLE2902());


  pService->start();

  // broadcast 
  pServer->getAdvertising()->start();
}

void loop() {
  double exampleDegrees = 59.05;
  pPitchCharacteristic->setValue((uint8_t*) &exampleDegrees, sizeof(double));
  pPitchCharacteristic->notify();
}
