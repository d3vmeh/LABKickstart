// LABKickstart - Reference BLE module
// Demonstrates the project-wide convention so future modules (load cell,
// IMU, etc.) all look the same to the Pi:
//
//   - Device name: "LK-<Module>-<id>"
//   - Shared service UUID + single events characteristic (notify)
//   - Each notification is one UTF-8 JSON object: {"channel": "...", "value": N}
//   - Notify on real events, or rate-limit continuous sensors (~50 Hz max)
//   - Re-start advertising on disconnect so the Pi can reconnect
//
// This sketch fakes a pitch reading; replace the value with a real sensor
// read (LSM303, MPU6050, etc.) when you copy it.
//
// Spec: firmware/device_interfaces/README.md

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---------- Project-wide UUIDs (do NOT change for new modules) ----------
#define SERVICE_UUID     "5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f"
#define EVENTS_CHAR_UUID "5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f"

// ---------- Per-module configuration ----------
static const char*    DEVICE_NAME       = "LK-IMU-01";
static const char*    PITCH_CHANNEL     = "pitch_deg";
static const uint32_t SAMPLE_PERIOD_MS  = 20;   // 50 Hz

// ---------- State ----------
BLECharacteristic* eventsChar = nullptr;
volatile bool      deviceConnected = false;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    deviceConnected = true;
    Serial.println("[BLE] central connected");
  }
  void onDisconnect(BLEServer*) override {
    deviceConnected = false;
    Serial.println("[BLE] central disconnected, re-advertising");
    BLEDevice::startAdvertising();
  }
};

void publishEvent(const char* channel, double value) {
  char payload[96];
  int n = snprintf(payload, sizeof(payload),
                   "{\"channel\":\"%s\",\"value\":%.4f}", channel, value);
  if (n <= 0) return;
  Serial.println(payload);
  if (deviceConnected && eventsChar) {
    eventsChar->setValue((uint8_t*)payload, (size_t)n);
    eventsChar->notify();
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.print("[boot] LABKickstart module ");
  Serial.println(DEVICE_NAME);

  BLEDevice::init(DEVICE_NAME);
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* svc = server->createService(SERVICE_UUID);
  eventsChar = svc->createCharacteristic(
      EVENTS_CHAR_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  eventsChar->addDescriptor(new BLE2902());
  svc->start();

  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  adv->setMinPreferred(0x06);
  BLEDevice::startAdvertising();

  Serial.print("[BLE] advertising as ");
  Serial.println(DEVICE_NAME);
}

void loop() {
  // Replace this stub with a real sensor read.
  static double fakePitch = 0;
  fakePitch += 0.5;
  if (fakePitch > 90) fakePitch = -90;

  publishEvent(PITCH_CHANNEL, fakePitch);

  delay(SAMPLE_PERIOD_MS);
}
