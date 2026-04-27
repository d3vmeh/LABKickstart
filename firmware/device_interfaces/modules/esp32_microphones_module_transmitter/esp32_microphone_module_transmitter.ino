#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>


#define SERVICE_UUID      "f30c13bf-c618-424d-aeb6-d035b933750f"
#define MIC_ARRAY_UUID    "25b65d1c-7440-4f2b-9284-8e01e5797d01"

#define BLE_DEVICE_NAME   "MIC2_Module"

BLECharacteristic* pMicCharacteristic;

const int MIC1_PIN = 4;
const int MIC2_PIN = 5;

const int SAMPLE_COUNT = 256;
const int SAMPLE_DELAY_US = 125;  // roughly 8 kHz per mic, not precision audio timing

struct __attribute__((packed)) Mic2Data {
  float rms1;
  float peak1;
  float mean1;

  float rms2;
  float peak2;
  float mean2;

  uint32_t timestamp_ms;
};

Mic2Data mic_data;

void readOneMic(int pin, float& rms, float& peak, float& mean) {
  int samples[SAMPLE_COUNT];
  long sum = 0;

  for (int i = 0; i < SAMPLE_COUNT; i++) {
    int raw = analogRead(pin);
    samples[i] = raw;
    sum += raw;
    delayMicroseconds(SAMPLE_DELAY_US);
  }

  mean = (float)sum / SAMPLE_COUNT;

  double sum_sq = 0.0;
  peak = 0.0;

  for (int i = 0; i < SAMPLE_COUNT; i++) {
    float centered = samples[i] - mean;
    float abs_val = fabs(centered);

    if (abs_val > peak) {
      peak = abs_val;
    }

    sum_sq += centered * centered;
  }

  rms = sqrt(sum_sq / SAMPLE_COUNT);
}

void readBothMics(Mic2Data& output) {
  float rms1 = 0.0f;
  float peak1 = 0.0f;
  float mean1 = 0.0f;

  float rms2 = 0.0f;
  float peak2 = 0.0f;
  float mean2 = 0.0f;

  readOneMic(MIC1_PIN, rms1, peak1, mean1);
  readOneMic(MIC2_PIN, rms2, peak2, mean2);

  output.rms1 = rms1;
  output.peak1 = peak1;
  output.mean1 = mean1;

  output.rms2 = rms2;
  output.peak2 = peak2;
  output.mean2 = mean2;

  output.timestamp_ms = millis();
}


void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("Starting ESP32-S3 two-microphone BLE transmitter...");

  analogReadResolution(12);
  analogSetPinAttenuation(MIC1_PIN, ADC_11db);
  analogSetPinAttenuation(MIC2_PIN, ADC_11db);

  BLEDevice::init(BLE_DEVICE_NAME);

  BLEServer* pServer = BLEDevice::createServer();
  BLEService* pService = pServer->createService(SERVICE_UUID);

  pMicCharacteristic = pService->createCharacteristic(
    MIC_ARRAY_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );

  pMicCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  pServer->getAdvertising()->start();

  Serial.print("BLE advertising started as: ");
  Serial.println(BLE_DEVICE_NAME);
  Serial.print("MIC_ARRAY_UUID: ");
  Serial.println(MIC_ARRAY_UUID);
}


void loop() {
  readBothMics(mic_data);

  pMicCharacteristic->setValue((uint8_t*)&mic_data, sizeof(Mic2Data));
  pMicCharacteristic->notify();

  Serial.print("mic1 rms=");
  Serial.print(mic_data.rms1);
  Serial.print(", peak=");
  Serial.print(mic_data.peak1);
  Serial.print(", mean=");
  Serial.print(mic_data.mean1);

  Serial.print(" | mic2 rms=");
  Serial.print(mic_data.rms2);
  Serial.print(", peak=");
  Serial.print(mic_data.peak2);
  Serial.print(", mean=");
  Serial.print(mic_data.mean2);

  Serial.print(" | t=");
  Serial.println(mic_data.timestamp_ms);

  delay(50);
}
