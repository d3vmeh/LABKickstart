#include "BLEDevice.h"

void setup() {
  delay(2000);
  BLEDevice::init("");

  Serial.begin(115200);
  // WiFi.mode(WIFI_STA);
}

void loop() {
  // Serial.print("ESP MAC Address: ");
  // Serial.println(WiFi.macAddress());
  Serial.print("ESP BLE Address: ");
  Serial.println(BLEDevice::getAddress().toString().c_str());
}
