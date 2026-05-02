/*  for BLE transmission  */
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>

#define SERVICE_UUID        "a13ebb02-0bce-4cab-a875-2659399c1da3"
#define BEAMBREAK_UUID      "c650e0f7-e67d-46cf-ba89-4fd287070199"

#define BLE_DEVICE_NAME   "BEAMBREAK_Module_2"

BLECharacteristic* pBeamCharacteristic;

// add a pin
#define LED_PIN 25

#define BLOCKED_LEVEL LOW   // Usually LOW for these IR sensors
#define DEBOUNCE_US 10000   // 10 milliseconds

const int BEAM_PIN = 18;

const uint8_t GATE_ID = 2;


struct __attribute__((packed)) BeamBreakData {
  uint8_t gate_id;
  uint8_t state;          // 1 = BLOCKED, 0 = CLEAR
};

int lastRawState = -1;
unsigned long lastEventTimeUs = 0;

class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer*) override {
    BLEDevice::startAdvertising();
  }
};

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Serial.println();
  // Serial.println("Starting ESP32-S3 Beam Break BLE transmitter...");

  pinMode(BEAM_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);

  lastRawState = digitalRead(BEAM_PIN);

  // Serial.print("Initial raw state: ");
  // Serial.println(lastRawState);

  // if (lastRawState == BLOCKED_LEVEL) {
  //   Serial.println("Initial interpreted state: BLOCKED");
  // } else {
  //   Serial.println("Initial interpreted state: CLEAR");
  // }

  // Start BLE
  BLEDevice::init(BLE_DEVICE_NAME);

  BLEServer* pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());   
  BLEService* pService = pServer->createService(SERVICE_UUID);

  pBeamCharacteristic = pService->createCharacteristic(
    BEAMBREAK_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );

  pBeamCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  pServer->getAdvertising()->start();

  // Serial.print("BLE advertising started as: ");
  // Serial.println(BLE_DEVICE_NAME);
  // Serial.print("Beam break characteristic UUID: ");
  // Serial.println(BEAMBREAK_UUID);
}



void loop() {
  int rawState = digitalRead(BEAM_PIN);

  if (rawState == BLOCKED_LEVEL) 
    digitalWrite(LED_PIN, HIGH);
  else
    digitalWrite(LED_PIN, LOW);

  unsigned long nowUs = micros();

  // Only send when state changes
  if (rawState != lastRawState) {
    // Simple debounce
    if (nowUs - lastEventTimeUs < DEBOUNCE_US) {
      return;
    }

    bool blocked = (rawState == BLOCKED_LEVEL);

    BeamBreakData data;
    data.gate_id = GATE_ID;    
    data.state = blocked ? 1 : 0;

    pBeamCharacteristic->setValue((uint8_t*)&data, sizeof(data));
    pBeamCharacteristic->notify();

    // debugging statements
    // Serial.print("Gate ");
    // Serial.print(data.gate_id);
    // Serial.print(" raw=");
    // Serial.print(rawState);
    // Serial.print(" state=");
    // Serial.print(blocked ? "BLOCKED" : "CLEAR");

    lastRawState = rawState;
    lastEventTimeUs = nowUs;

    // Serial.println();
  }

  // delay(1);
  
}
