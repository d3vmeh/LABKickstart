/* for BLE transmission   */
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>

#define SERVICE_UUID      "f30c13bf-c618-424d-aeb6-d035b933750f"
#define BEAMBREAK_UUID    "7c2b6f3a-4a8c-4d24-8f8b-32e2a5c76f10"

#define BLE_DEVICE_NAME   "BEAMBREAK_Module"

BLECharacteristic* pBeamCharacteristic;

// Separate LED Pins
#define LED_A_PIN 23
#define LED_B_PIN 25

#define BLOCKED_LEVEL LOW 
#define DEBOUNCE_US 10000 

// Separate Sensor Pins
const int PIN_A = 18; 
const int PIN_B = 19;

// Separate IDs for the data packet
const uint8_t ID_A = 1;
const uint8_t ID_B = 2;

struct __attribute__((packed)) BeamBreakData {
  uint8_t gate_id;
  uint8_t state; 
};

// Tracking for Sensor A
int lastStateA = -1;
unsigned long lastTimeA = 0;

// Tracking for Sensor B
int lastStateB = -1;
unsigned long lastTimeB = 0;

class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer*) override {
    BLEDevice::startAdvertising();
  }
};

void setup() {
  // Serial.begin(115200);
  delay(1000);

  // Setup LEDs
  pinMode(LED_A_PIN, OUTPUT);
  pinMode(LED_B_PIN, OUTPUT);
  
  // Setup Sensors
  pinMode(PIN_A, INPUT_PULLUP);
  pinMode(PIN_B, INPUT_PULLUP);

  lastStateA = digitalRead(PIN_A);
  lastStateB = digitalRead(PIN_B);

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
}

void loop() {
  unsigned long now = micros();

  // Read both sensors
  int rawA = digitalRead(PIN_A);
  int rawB = digitalRead(PIN_B);

  // --- LED LOGIC ---
  // LED A follows Sensor A
  if (rawA == BLOCKED_LEVEL) {
    digitalWrite(LED_A_PIN, HIGH);
  } else {
    digitalWrite(LED_A_PIN, LOW);
  }

  // LED B follows Sensor B
  if (rawB == BLOCKED_LEVEL) {
    digitalWrite(LED_B_PIN, HIGH);
  } else {
    digitalWrite(LED_B_PIN, LOW);
  }

  // --- Handle Sensor A BLE ---
  if (rawA != lastStateA) {
    if (now - lastTimeA >= DEBOUNCE_US) {
      BeamBreakData data;
      data.gate_id = ID_A;
      data.state = (rawA == BLOCKED_LEVEL) ? 1 : 0;

      pBeamCharacteristic->setValue((uint8_t*)&data, sizeof(data));
      pBeamCharacteristic->notify();

      lastStateA = rawA;
      lastTimeA = now;
    }
  }

  // --- Handle Sensor B BLE ---
  if (rawB != lastStateB) {
    if (now - lastTimeB >= DEBOUNCE_US) {
      BeamBreakData data;
      data.gate_id = ID_B;
      data.state = (rawB == BLOCKED_LEVEL) ? 1 : 0;

      pBeamCharacteristic->setValue((uint8_t*)&data, sizeof(data));
      pBeamCharacteristic->notify();

      lastStateB = rawB;
      lastTimeB = now;
    }
  }

  // delay(1);
}