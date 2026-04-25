#include "Wire.h"
#include "Adafruit_VL6180X.h"
#include "stdint.h"

Adafruit_VL6180X ToF_sensor;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  if (!ToF_sensor.begin()) {
    Serial.println("Sensor Init Fail");
    while(1);
  }
}

void loop() {
  uint8_t distance = ToF_sensor.readRange();
  uint8_t status = ToF_sensor.readRangeStatus();

  if (status == VL6180X_ERROR_NONE) {
    Serial.print("Distance: ");
    Serial.println(distance);
  } else {
    Serial.println("Error");
  }
  
  delay(50);
}
