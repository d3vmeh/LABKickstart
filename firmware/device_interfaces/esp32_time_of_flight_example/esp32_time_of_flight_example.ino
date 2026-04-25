#include "Wire.h"
#include "VL6180X.h"
#include "stdint.h"

VL6180X ToF_sensor;

#define SCALE_FACTOR 2

void i2c_regWrite(uint16_t reg, uint8_t value) {
  Wire.beginTransmission(0x29);
  Wire.write(reg >> 8);
  Wire.write(reg & 0xFF);
  Wire.write(value);
  uint8_t error = Wire.endTransmission();
  if (error != 0) {
    Serial.println("I2C Error");
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  ToF_sensor.init();
  ToF_sensor.configureDefault();
  ToF_sensor.setScaling(SCALE_FACTOR);
  ToF_sensor.setTimeout(500);
}

void loop() {
  // Serial.print("Scaling: ");
  // Serial.println(ToF_sensor.getScaling());

  Serial.print("Distance: ");
  Serial.print(ToF_sensor.readRangeSingleMillimeters());

  if (ToF_sensor.timeoutOccurred()) { Serial.print(" TIMEOUT"); }
  
  Serial.println();
  
  delay(50);
}
