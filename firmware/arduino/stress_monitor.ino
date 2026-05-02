#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <avr/pgmspace.h>

// ---------------- HARDWARE CONSTANTS ----------------
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
#define RED_LED        8
#define BLUE_LED       9
#define DHTPIN         2
#define DHTTYPE        DHT11

// ---------------- TWO-COLOUR OLED ZONE MAP ----------
//
//  Rows  0 – 15  → YELLOW zone  (BPM)
//  Rows 16 – 26  → BLUE zone    (Stress + Temp)
//  Row       27  → Divider line
//  Rows 28 – 63  → BLUE zone    (ECG — 36px tall)
//
#define YELLOW_TOP     0
#define YELLOW_HEIGHT  16
#define TEXT_ROW       17
#define DIVIDER_ROW    27
#define ECG_TOP        28
#define ECG_HEIGHT     (SCREEN_HEIGHT - ECG_TOP)
#define ECG_BASELINE   (ECG_TOP + ECG_HEIGHT / 2)
#define ECG_COLS       SCREEN_WIDTH

// ---------------- ECG AMPLITUDE ---------------------
#define ECG_AMP_LOW    10
#define ECG_AMP_NORMAL 13
#define ECG_AMP_MOD    15
#define ECG_AMP_HIGH   17

// ---------------- TIMING ----------------------------
#define DISPLAY_INTERVAL  1000
#define DHT_INTERVAL      2000
#define ECG_INTERVAL      28
#define OLED_INTERVAL     55
#define SERIAL_INTERVAL   100

// ---------------- LED BLINK PERIODS -----------------
#define BLINK_HIGH   200
#define BLINK_MOD    600
#define BLINK_LOW    1500

// ---------------- STRESS ENUM -----------------------
enum StressLevel : uint8_t {
  STRESS_NO_DATA = 0,
  STRESS_LOW,
  STRESS_NORMAL,
  STRESS_MODERATE,
  STRESS_HIGH
};

const char S0[] PROGMEM = "NO DATA ";
const char S1[] PROGMEM = "LOW     ";
const char S2[] PROGMEM = "NORMAL  ";
const char S3[] PROGMEM = "MODERATE";
const char S4[] PROGMEM = "HIGH    ";
const char* const STRESS_LABELS[] PROGMEM = { S0, S1, S2, S3, S4 };

// ---------------- PQRST IN PROGMEM ------------------
const float PQRST[] PROGMEM = {
  0.00, 0.00, 0.00, 0.00, 0.00,
  0.08, 0.15, 0.20, 0.15, 0.08,
  0.00, 0.00, 0.00, 0.00,
  -0.10, -0.20,
  0.50, 0.85, 1.00, 0.85, 0.50,
  -0.25, -0.15,
  0.00, 0.00, 0.00,
  0.08, 0.18, 0.28, 0.30, 0.28, 0.18, 0.08,
  0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00
};
#define PQRST_LEN 40

// ---------------- OBJECTS ---------------------------
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
MAX30105 particleSensor;
DHT dht(DHTPIN, DHTTYPE);

// ---------------- HEART RATE ------------------------
const byte RATE_SIZE = 4;
uint16_t rates[RATE_SIZE];
byte  rateSpot    = 0;
long  lastBeat    = 0;
float beatAvg     = 0;
float lastBeatAvg = -1;

// ---------------- ENVIRONMENT -----------------------
float temperature = 0;
float humidity    = 0;

// ---------------- STATE -----------------------------
StressLevel stressLevel = STRESS_NO_DATA;

// ---------------- TIMING ----------------------------
unsigned long lastDisplayUpdate = 0;
unsigned long lastDHTRead       = 0;
unsigned long lastECGUpdate     = 0;
unsigned long lastOLED          = 0;
unsigned long lastSerialOut     = 0;

// ---------------- ECG BUFFER ------------------------
int8_t ecgBuffer[ECG_COLS];
int    ecgWritePos = 0;
float  pqrstIndex  = 0.0f;
float  pqrstStep   = 1.0f;

// ---------------- DIRTY FLAGS -----------------------
int     lastBPM    = -1;
uint8_t lastStress = 255;
int     lastTemp10 = -9999;

// ======================================================
void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);

  pinMode(RED_LED,  OUTPUT);
  pinMode(BLUE_LED, OUTPUT);

  // Ensure LEDs start OFF cleanly
  digitalWrite(RED_LED,  LOW);
  digitalWrite(BLUE_LED, LOW);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("OLED init failed!"));
    while (1);
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(16, 2);  display.print(F("STRESS MONITOR"));
  display.setCursor(34, 11); display.print(F("Starting..."));
  display.display();
  delay(1500);

  if (!particleSensor.begin(Wire, 400000UL)) {
    Serial.println(F("MAX30102 not found!"));
    while (1);
  }
  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x0A);
  particleSensor.setPulseAmplitudeGreen(0);

  dht.begin();

  for (int i = 0; i < ECG_COLS; i++) ecgBuffer[i] = (int8_t)ECG_BASELINE;

  Serial.println(F("Ready."));
}

// ======================================================
void loop() {

  // ── 1. HEART RATE ───────────────────────────────────
  long irValue = particleSensor.getIR();

  if (irValue > 50000) {
    if (checkForBeat(irValue)) {
      long delta = millis() - lastBeat;
      lastBeat   = millis();
      float bpm  = 60000.0f / (float)delta;

      if (bpm > 40 && bpm < 200) {
        rates[rateSpot++] = (uint16_t)bpm;
        rateSpot %= RATE_SIZE;
        float sum = 0;
        for (byte x = 0; x < RATE_SIZE; x++) sum += rates[x];
        beatAvg = sum / RATE_SIZE;
      }
    }
  } else {
    beatAvg  = 0;
    rateSpot = 0;
    memset(rates, 0, sizeof(rates));
  }

  // ── 2. DHT ──────────────────────────────────────────
  if (millis() - lastDHTRead > DHT_INTERVAL) {
    lastDHTRead = millis();
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t) && !isnan(h)) { temperature = t; humidity = h; }
  }

  // ── 3. LEDs ─────────────────────────────────────────
  handleLEDs();

  // ── 4. ECG BUFFER ───────────────────────────────────
  if (millis() - lastECGUpdate > ECG_INTERVAL) {
    lastECGUpdate = millis();
    if (beatAvg != lastBeatAvg) {
      lastBeatAvg = beatAvg;
      if (beatAvg > 0) {
        float upb = (60.0f / beatAvg) * (1000.0f / ECG_INTERVAL);
        pqrstStep = (float)PQRST_LEN / upb;
      }
    }
    updateECGBuffer();
  }

  // ── 5. STRESS RECALC ────────────────────────────────
  if (millis() - lastDisplayUpdate > DISPLAY_INTERVAL) {
    lastDisplayUpdate = millis();
    calculateStress();
  }

  // ── 6. SERIAL JSON ──────────────────────────────────
  if (millis() - lastSerialOut > SERIAL_INTERVAL) {
    lastSerialOut = millis();
    sendJSON();
  }

  // ── 7. UNIFIED OLED RENDER ──────────────────────────
  if (millis() - lastOLED > OLED_INTERVAL) {
    lastOLED = millis();
    renderOLED();
  }
}

// ======================================================
// LED CONTROL
// FIX: uses static variables to track last state
// digitalWrite is ONLY called when state actually changes
// This eliminates thousands of unnecessary GPIO switches per second
// which were causing power rail noise that corrupted I2C / OLED
void handleLEDs() {
  static bool lastRedState  = false;
  static bool lastBlueState = false;

  bool newRed  = false;
  bool newBlue = false;

  switch (stressLevel) {
    case STRESS_HIGH:
      newRed = (millis() % BLINK_HIGH < (BLINK_HIGH / 2));
      break;
    case STRESS_MODERATE:
      newRed = (millis() % BLINK_MOD < (BLINK_MOD / 2));
      break;
    case STRESS_NORMAL:
      newBlue = true;
      break;
    case STRESS_LOW:
      newRed = (millis() % BLINK_LOW < (BLINK_LOW / 2));
      break;
    default:   // NO DATA — both off
      break;
  }

  // Only write to GPIO pin if the state has changed
  if (newRed  != lastRedState)  {
    digitalWrite(RED_LED,  newRed  ? HIGH : LOW);
    lastRedState  = newRed;
  }
  if (newBlue != lastBlueState) {
    digitalWrite(BLUE_LED, newBlue ? HIGH : LOW);
    lastBlueState = newBlue;
  }
}

// ======================================================
// ECG BUFFER — pre-computed Y pixel positions
void updateECGBuffer() {
  int8_t yPixel;

  if (beatAvg <= 0) {
    yPixel     = (int8_t)ECG_BASELINE;
    pqrstIndex = 0.0f;
  } else {
    int idx = (int)pqrstIndex;
    if (idx >= PQRST_LEN) idx = 0;
    float sample = pgm_read_float(&PQRST[idx]);

    uint8_t amp;
    switch (stressLevel) {
      case STRESS_HIGH:     amp = ECG_AMP_HIGH;   break;
      case STRESS_MODERATE: amp = ECG_AMP_MOD;    break;
      case STRESS_NORMAL:   amp = ECG_AMP_NORMAL; break;
      default:              amp = ECG_AMP_LOW;    break;
    }

    int y = ECG_BASELINE - (int)(sample * amp);
    yPixel = (int8_t)constrain(y, ECG_TOP, ECG_TOP + ECG_HEIGHT - 1);

    pqrstIndex += pqrstStep;
    if (pqrstIndex >= PQRST_LEN) pqrstIndex -= PQRST_LEN;
  }

  ecgBuffer[ecgWritePos] = yPixel;
  ecgWritePos = (ecgWritePos + 1) % ECG_COLS;
}

// ======================================================
// UNIFIED OLED RENDER — one display.display() call per frame
void renderOLED() {

  // ── YELLOW ZONE: BPM (rows 0–15) ──────────────────
  bool bpmChanged = ((int)beatAvg != lastBPM);
  if (bpmChanged) {
    lastBPM = (int)beatAvg;
    display.fillRect(0, YELLOW_TOP, SCREEN_WIDTH, YELLOW_HEIGHT, SSD1306_BLACK);
    display.setTextColor(SSD1306_WHITE);

    if (beatAvg > 0) {
      display.setTextSize(2);
      char bpmStr[10];
      snprintf(bpmStr, sizeof(bpmStr), "%d BPM", (int)beatAvg);
      int16_t x1, y1; uint16_t w, h;
      display.getTextBounds(bpmStr, 0, 0, &x1, &y1, &w, &h);
      display.setCursor((SCREEN_WIDTH - w) / 2, 1);
      display.print(bpmStr);
    } else {
      display.setTextSize(1);
      display.setCursor(16, 5);
      display.print(F("-- PLACE FINGER --"));
    }
  }

  // ── BLUE TEXT ZONE: Stress + Temp (rows 17–26) ────
  bool stressChanged = (stressLevel != lastStress);
  int  tempNow10     = (int)(temperature * 10);
  bool tempChanged   = (tempNow10 != lastTemp10);

  if (stressChanged || tempChanged) {
    lastStress = stressLevel;
    lastTemp10 = tempNow10;

    display.fillRect(0, TEXT_ROW, SCREEN_WIDTH, DIVIDER_ROW - TEXT_ROW, SSD1306_BLACK);
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);

    // Stress — left
    char stressBuf[9];
    strcpy_P(stressBuf, (char*)pgm_read_ptr(&STRESS_LABELS[stressLevel]));
    display.setCursor(0, TEXT_ROW);
    display.print(stressBuf);

    // Temp — right aligned
    char tempBuf[8];
    if (temperature > 0)
      snprintf(tempBuf, sizeof(tempBuf), "%.1fC", temperature);
    else
      snprintf(tempBuf, sizeof(tempBuf), "--C");
    int tempWidth = strlen(tempBuf) * 6;
    display.setCursor(SCREEN_WIDTH - tempWidth, TEXT_ROW);
    display.print(tempBuf);
  }

  // ── DIVIDER LINE (row 27) ──────────────────────────
  display.drawFastHLine(0, DIVIDER_ROW, SCREEN_WIDTH, SSD1306_WHITE);

  // ── BLUE ECG ZONE (rows 28–63) ────────────────────
  display.fillRect(0, ECG_TOP, SCREEN_WIDTH, ECG_HEIGHT, SSD1306_BLACK);

  if (beatAvg <= 0) {
    display.drawFastHLine(0, ECG_BASELINE, SCREEN_WIDTH, SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(28, ECG_BASELINE - 9);
    display.print(F("NO SIGNAL"));

  } else {
    // drawLine between adjacent points — no gaps in waveform
    for (int col = 0; col < ECG_COLS - 1; col++) {
      int8_t y0 = ecgBuffer[(ecgWritePos + col)     % ECG_COLS];
      int8_t y1 = ecgBuffer[(ecgWritePos + col + 1) % ECG_COLS];
      display.drawLine(col, (int)y0, col + 1, (int)y1, SSD1306_WHITE);
    }

    // Blinking write-head cursor
    if (millis() % 600 < 300) {
      int8_t curY = ecgBuffer[(ecgWritePos - 1 + ECG_COLS) % ECG_COLS];
      display.drawPixel(ecgWritePos % ECG_COLS, (int)curY, SSD1306_WHITE);
    }
  }

  // ONE display call for the entire frame
  display.display();
}

// ======================================================
void calculateStress() {
  if (beatAvg == 0) { stressLevel = STRESS_NO_DATA; return; }
  if      (beatAvg < 75)   stressLevel = STRESS_LOW;
  else if (beatAvg < 90)   stressLevel = STRESS_NORMAL;
  else if (beatAvg <= 110) stressLevel = STRESS_MODERATE;
  else                     stressLevel = STRESS_HIGH;
  if (temperature > 30 && humidity > 70)
    if (stressLevel < STRESS_HIGH)
      stressLevel = (StressLevel)(stressLevel + 1);
}

// ======================================================
void sendJSON() {
  int idx = (int)pqrstIndex % PQRST_LEN;
  float ecgVal = (beatAvg > 0) ? pgm_read_float(&PQRST[idx]) : 0.0f;

  char stressBuf[9];
  strcpy_P(stressBuf, (char*)pgm_read_ptr(&STRESS_LABELS[stressLevel]));
  for (int i = 7; i >= 0 && stressBuf[i] == ' '; i--) stressBuf[i] = '\0';

  Serial.print(F("{\"bpm\":"));      Serial.print((int)beatAvg);
  Serial.print(F(",\"stress\":\"")); Serial.print(stressBuf);
  Serial.print(F("\",\"temp\":"));   Serial.print(temperature, 1);
  Serial.print(F(",\"hum\":"));      Serial.print((int)humidity);
  Serial.print(F(",\"ecg\":"));      Serial.print(ecgVal, 3);
  Serial.println(F(",\"connected\":true}"));
}
