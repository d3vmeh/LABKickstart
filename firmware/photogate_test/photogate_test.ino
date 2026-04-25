// LABKickstart - Photogate Test Module
// One IR beam-break sensor, one ESP32, BLE notifications.
//
// Wiring (typical 3-pin IR break-beam receiver module):
//   VCC -> 3.3V
//   GND -> GND
//   OUT -> GPIO 4   (configurable below; see BEAM_PIN)
//
// Most receiver modules pull the output LOW when the beam is broken and HIGH
// when it is intact. If yours is inverted, flip BEAM_BROKEN_LEVEL below.
//
// Behavior:
//   - Watches the input pin via an interrupt on CHANGE.
//   - On a falling edge (beam broken) it records the timestamp.
//   - On the rising edge (beam restored) it computes the duration and:
//       - prints a JSON event over USB serial (115200 baud) for debugging
//       - publishes the same JSON as a BLE notification on the events
//         characteristic, so the Pi can subscribe and consume events.
//
// Protocol (project-wide convention; see firmware/device_interfaces/README.md):
//   one JSON object per BLE notification, shape {"channel": "...", "value": N}
//
//   {"channel":"gate_A_break_us","value":59917}
//
// The Pi maps each event directly onto a Sample(channel, value).

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---------- Configuration ----------
static const int      BEAM_PIN            = 6;
static const int      BEAM_BROKEN_LEVEL   = LOW;          // most modules: LOW = broken
static const char*    DEVICE_NAME         = "LK-Photogate-A";
static const char*    GATE_LABEL          = "A";
static const uint32_t MIN_BREAK_US        = 200;          // debounce: ignore < 200 us breaks
static const uint32_t HEARTBEAT_MS        = 5000;         // serial-only "still alive" log

// Shared between this project's photogate firmwares (gate A and gate B both
// implement the same service; the device name distinguishes them):
#define SERVICE_UUID     "5b1e0001-9e8d-4f3a-b50f-1a2b3c4d5e6f"
#define EVENTS_CHAR_UUID "5b1e0002-9e8d-4f3a-b50f-1a2b3c4d5e6f"

// ---------- State ----------
BLECharacteristic* eventsChar = nullptr;
volatile bool      deviceConnected = false;

volatile uint32_t  breakStartUs        = 0;
volatile uint32_t  pendingBreakUs      = 0;
volatile bool      eventReady          = false;

// ---------- Beam ISR ----------
void IRAM_ATTR onBeamChange() {
  uint32_t now = micros();
  int level = digitalRead(BEAM_PIN);
  if (level == BEAM_BROKEN_LEVEL) {
    breakStartUs = now;
  } else if (breakStartUs != 0) {
    uint32_t dur = now - breakStartUs;
    breakStartUs = 0;
    if (dur >= MIN_BREAK_US) {
      pendingBreakUs = dur;
      eventReady = true;
    }
  }
}

// ---------- BLE callbacks ----------
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

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.print("[boot] LABKickstart photogate test, gate=");
  Serial.println(GATE_LABEL);

  pinMode(BEAM_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BEAM_PIN), onBeamChange, CHANGE);
  Serial.print("[boot] watching beam on GPIO ");
  Serial.println(BEAM_PIN);

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
  adv->setMinPreferred(0x06);   // helps iOS / generic centrals connect quickly
  BLEDevice::startAdvertising();

  Serial.print("[BLE] advertising as ");
  Serial.println(DEVICE_NAME);
}

// ---------- Main loop ----------
void loop() {
  // Drain a pending event, if any.
  if (eventReady) {
    noInterrupts();
    uint32_t dur = pendingBreakUs;
    eventReady = false;
    interrupts();

    char payload[80];
    int n = snprintf(payload, sizeof(payload),
                     "{\"channel\":\"gate_%s_break_us\",\"value\":%u}",
                     GATE_LABEL, (unsigned)dur);
    if (n > 0) {
      Serial.println(payload);
      if (deviceConnected && eventsChar) {
        eventsChar->setValue((uint8_t*)payload, (size_t)n);
        eventsChar->notify();
      }
    }
  }

  // Cheap heartbeat so you can tell over serial that the firmware is alive
  // even when no breaks have happened.
  static uint32_t lastBeat = 0;
  uint32_t nowMs = millis();
  if (nowMs - lastBeat > HEARTBEAT_MS) {
    lastBeat = nowMs;
    Serial.print("[hb] connected=");
    Serial.print(deviceConnected ? "yes" : "no");
    Serial.print(" beam=");
    Serial.println(digitalRead(BEAM_PIN) == BEAM_BROKEN_LEVEL ? "BROKEN" : "intact");
  }

  delay(2);
}
