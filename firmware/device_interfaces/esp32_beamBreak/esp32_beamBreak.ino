/*
  this is just a simple sketch for interfacing beam break sensor
  if ir pin is LOW =  Beam Broken
  if ir pin is HIGH = Beam not broken
  Notice that the input pin must be set to input pullup
*/


#define IR_PIN 17
#define LED_PIN 23

int sensorState = 0;

void setup() {
  // set up ir pin for pullup
  pinMode(IR_PIN, INPUT_PULLUP);

  // LED init
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(9600);
}

void loop() {
  sensorState = digitalRead(IR_PIN);

  if (sensorState == LOW) {
    Serial.println("Beam Broken");
    digitalWrite(LED_PIN, HIGH);
  } else {
    Serial.println("Beam not broken");
    digitalWrite(LED_PIN, LOW);
  }
}
