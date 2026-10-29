// Inspection sequencer: HC-SR04 + LCD1602 (I2C) + RGB LED + 2 tact switches
// Board: Arduino Uno

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- User settings ----------------
const uint8_t PIN_R         = 3;   // RGB red (PWM)
const uint8_t PIN_G         = 5;   // RGB green (PWM)
const uint8_t PIN_B         = 6;   // RGB blue (PWM)
const uint8_t PIN_TRIG      = 7;   // HC-SR04 trigger
const uint8_t PIN_ECHO      = 8;   // HC-SR04 echo
const uint8_t PIN_BTN_LEFT  = 9;   // Left tact switch (start capture)
const uint8_t PIN_BTN_RIGHT = 11;  // Right tact switch (reset)

const bool COMMON_ANODE = false;   // Set to true if the RGB module is common anode
const uint8_t LCD_ADDR  = 0x27;    // Try 0x3F if the LCD shows nothing

const float DETECT_DISTANCE_CM = 5.0;     // Turn ON at or below this distance
const float RELEASE_DISTANCE_CM = 7.0;    // Stay ON until the distance goes above this
const unsigned long RELEASE_HOLD_MS = 500; // Must stay away this long before turning OFF
const unsigned long DETECTING_MS = 3000;  // Minimum "DETECTING..." display time
const unsigned long RESULT_TIMEOUT_MS = 20000;  // Give up waiting for the PC result after this time
const unsigned long RESET_MS     = 3000;  // "RESET" display time
const unsigned long SENSOR_INTERVAL_MS = 60;
const unsigned long DEBOUNCE_MS  = 30;
const unsigned long SERIAL_PRINT_MS = 1000;  // Distance print interval (1 second)
const unsigned long SERIAL_BAUD = 9600;      // Serial monitor speed

// ---------------- LED colors (R, G, B: 0-255) ----------------
const uint8_t COLOR_WHITE[3] = {255, 200, 200};
const uint8_t COLOR_RED[3]   = {255, 0, 0};
const uint8_t COLOR_GREEN[3] = {0, 255, 0};
const uint8_t COLOR_OFF[3]   = {0, 0, 0};

// ---------------- Globals ----------------
LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);

enum State { ST_IDLE, ST_READY, ST_DETECTING, ST_FAIL, ST_PASS, ST_RESET };
State state = ST_IDLE;
unsigned long stateStart = 0;

// Object presence (filtered)
bool objectPresent = false;
uint8_t nearCount = 0;
uint8_t farCount = 0;
unsigned long lastNearTime = 0;  // Last time an object was seen inside the release distance
unsigned long lastSensorTime = 0;
float lastDistanceCm = -1.0;             // Latest measured distance
unsigned long lastSerialPrintTime = 0;   // Last time the distance was printed

// Result received from the PC: 0 = none, 1 = PASS, 2 = FAIL
uint8_t pendingResult = 0;
char rxBuf[16];                          // Receive buffer for one line from the PC
uint8_t rxLen = 0;

// Button debounce data
struct Button {
  uint8_t pin;
  bool lastReading;
  bool stableState;
  unsigned long lastChange;
};
Button btnLeft  = {PIN_BTN_LEFT,  HIGH, HIGH, 0};
Button btnRight = {PIN_BTN_RIGHT, HIGH, HIGH, 0};

// ---------------- Helpers ----------------
void setColor(const uint8_t c[3]) {
  uint8_t r = c[0];
  uint8_t g = c[1];
  uint8_t b = c[2];
  if (COMMON_ANODE) {
    r = 255 - r;
    g = 255 - g;
    b = 255 - b;
  }
  analogWrite(PIN_R, r);
  analogWrite(PIN_G, g);
  analogWrite(PIN_B, b);
}

void showText(const char *text) {
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(text);
}

float readDistanceCm() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long duration = pulseIn(PIN_ECHO, HIGH, 30000UL);  // 30 ms timeout
  if (duration == 0) {
    return -1.0;  // No echo
  }
  return duration * 0.0343 / 2.0;
}

void updateObjectPresence(unsigned long now) {
  if (now - lastSensorTime < SENSOR_INTERVAL_MS) {
    return;
  }
  lastSensorTime = now;

  float d = readDistanceCm();
  lastDistanceCm = d;
  bool validReading = (d > 0.0);  // false means "no echo", which is ignored below

  if (!objectPresent) {
    // Turn ON only after 3 valid near readings in a row
    if (validReading && d <= DETECT_DISTANCE_CM) {
      if (nearCount < 255) nearCount++;
    } else if (validReading) {
      nearCount = 0;  // Valid reading but too far
    }
    // "No echo" readings do not change nearCount

    if (nearCount >= 3) {
      objectPresent = true;
      lastNearTime = now;
      nearCount = 0;
    }
  } else {
    // Refresh the timer while the object is inside the release distance
    if (validReading && d <= RELEASE_DISTANCE_CM) {
      lastNearTime = now;
    }
    // Turn OFF only if nothing was seen inside the release distance for a while
    if (now - lastNearTime >= RELEASE_HOLD_MS) {
      objectPresent = false;
      nearCount = 0;
    }
  }
}

// Prints the latest distance once per second
void printDistanceEvery1s(unsigned long now) {
  if (now - lastSerialPrintTime < SERIAL_PRINT_MS) {
    return;
  }
  lastSerialPrintTime = now;

  Serial.print("Distance: ");
  if (lastDistanceCm < 0.0) {
    Serial.print("no echo");
  } else {
    Serial.print(lastDistanceCm, 1);
    Serial.print(" cm");
  }
  Serial.println(objectPresent ? "YES" : "NO");
}

// Reads lines from the PC. Only "PASS" or "FAIL" is accepted, and only while DETECTING
void readPcMessages() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      rxBuf[rxLen] = '\0';
      if (state == ST_DETECTING) {
        if (strcmp(rxBuf, "PASS") == 0) pendingResult = 1;
        else if (strcmp(rxBuf, "FAIL") == 0) pendingResult = 2;
      }
      rxLen = 0;
    } else if (rxLen < sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = c;
    }
  }
}

// Returns true once when the button is pressed (falling edge, debounced)
bool buttonPressed(Button &b, unsigned long now) {
  bool reading = digitalRead(b.pin);
  if (reading != b.lastReading) {
    b.lastChange = now;
    b.lastReading = reading;
  }
  if ((now - b.lastChange) > DEBOUNCE_MS && reading != b.stableState) {
    b.stableState = reading;
    if (b.stableState == LOW) {
      return true;
    }
  }
  return false;
}

// ---------------- State transitions ----------------
void enterIdle(unsigned long now) {
  state = ST_IDLE;
  stateStart = now;
  setColor(COLOR_OFF);
  lcd.clear();
  lcd.noBacklight();
  Serial.println("[STATE] IDLE (LED off, LCD off)");
}

void enterReady(unsigned long now) {
  state = ST_READY;
  stateStart = now;
  setColor(COLOR_WHITE);
  showText("READY");
  Serial.println("[STATE] READY (LED white, LCD: READY)");
}

void enterDetecting(unsigned long now) {
  state = ST_DETECTING;
  stateStart = now;
  pendingResult = 0;
  setColor(COLOR_WHITE);
  showText("DETECTING...");
  Serial.println("[STATE] DETECTING (LCD: DETECTING...)");
  Serial.println("CAPTURE");  // Command for the PC program
}

void enterFail(unsigned long now) {
  state = ST_FAIL;
  stateStart = now;
  setColor(COLOR_RED);
  showText("FAIL");
  Serial.println("[STATE] FAIL (LED red, LCD: FAIL)");
}

void enterPass(unsigned long now) {
  state = ST_PASS;
  stateStart = now;
  setColor(COLOR_GREEN);
  showText("PASS");
  Serial.println("[STATE] PASS (LED green, LCD: PASS)");
}

void enterReset(unsigned long now) {
  state = ST_RESET;
  stateStart = now;
  setColor(COLOR_OFF);
  showText("RESET");
  Serial.println("[STATE] RESET (LED off, LCD: RESET, 3 sec)");
}

// ---------------- Arduino entry points ----------------
void setup() {
  pinMode(PIN_R, OUTPUT);
  pinMode(PIN_G, OUTPUT);
  pinMode(PIN_B, OUTPUT);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_BTN_LEFT, INPUT_PULLUP);
  pinMode(PIN_BTN_RIGHT, INPUT_PULLUP);

  Serial.begin(SERIAL_BAUD);
  Serial.println("=== Inspection sequencer started ===");

  lcd.init();
  enterIdle(millis());
}

void loop() {
  unsigned long now = millis();

  updateObjectPresence(now);
  printDistanceEvery1s(now);
  readPcMessages();
  bool leftPressed  = buttonPressed(btnLeft, now);
  bool rightPressed = buttonPressed(btnRight, now);

  if (leftPressed) {
    Serial.println("[BUTTON] LEFT pressed");
  }
  if (rightPressed) {
    Serial.println("[BUTTON] RIGHT pressed");
  }

  // Right switch always triggers reset
  if (rightPressed) {
    enterReset(now);
    return;
  }

  switch (state) {
    case ST_IDLE:
      if (objectPresent) enterReady(now);
      break;

    case ST_READY:
      if (!objectPresent) {
        enterIdle(now);
      } else if (leftPressed) {
        enterDetecting(now);
      }
      break;

    case ST_DETECTING:
      if (pendingResult != 0 && now - stateStart >= DETECTING_MS) {
        if (pendingResult == 1) enterPass(now);
        else enterFail(now);
      } else if (now - stateStart >= RESULT_TIMEOUT_MS) {
        Serial.println("[WARN] No result from PC, treating as FAIL");
        enterFail(now);
      }
      break;

    case ST_FAIL:
    case ST_PASS:
      // Stays on the result until the object leaves or the reset switch is pressed
      if (!objectPresent) enterIdle(now);
      break;

    case ST_RESET:
      if (now - stateStart >= RESET_MS) enterIdle(now);  // Back to step 1
      break;
  }
}