#include "WiFi.h"

void setup() {
  delay(2000);
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
}

void loop() {
  Serial.print("ESP MAC Address: ");
  Serial.println(WiFi.macAddress());
}
