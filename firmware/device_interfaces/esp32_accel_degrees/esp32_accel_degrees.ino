#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_Accel.h>

// this is just setting an ID number i believe
Adafruit_LSM303_Accel_Unified accel = Adafruit_LSM303_Accel_Unified(54321);

void setup() {
  Serial.begin(115200);
  
  // initialize accelerometer
  if (!accel.begin()) {
    Serial.println("NO accel detected.");
    while (1);
  }
}

void loop() {
  sensors_event_t event;
  accel.getEvent(&event);

  // raw accel values
  double x = event.acceleration.x;
  double y = event.acceleration.y;
  double z = event.acceleration.z;

  // calculate pitch and roll in degrees
  double pitch = atan2(-x, sqrt(y * y + z * z)) * SENSORS_RADS_TO_DPS;

  double roll = atan2(y, z) * SENSORS_RADS_TO_DPS;

  // now we have all of our data
  Serial.print("Raw X: "); 
  Serial.print(x);
  Serial.println();

  Serial.print("Raw Y: ");
  Serial.print(y);
  Serial.println();

  Serial.print("Raw Z: ");
  Serial.print(z);
  Serial.println();

  Serial.print("Pitch degrees: ");
  Serial.print(pitch);
  Serial.println();

  Serial.print("Roll degrees: ");
  Serial.print(roll);
  
  Serial.println("\n\n\n\n");

  delay(100);
}
