#include <Arduino.h>
#include <FastLED.h>

// =================== LED CONFIG ===================
#define NUM_LEDS 300
#define DATA_PIN 4

CRGB leds[NUM_LEDS];

static Stream &CTRL = Serial;
static const uint32_t CTRL_BAUD = 115200;

// =================== PARSER ===================
static char lineBuf[80];
static uint8_t linePos = 0;
static bool autoShow = true;
static uint8_t brightness = 128;

// =================== STROBE STATE ===================
// Strobe is done by changing FastLED global brightness (does NOT modify leds[] colors).
static bool strobeEnabled = false;
static uint8_t strobeMin = 0;
static uint16_t strobeStepMs = 10;
static uint8_t strobeCur = 128;
static int8_t strobeDir = -1;     // -1 fading down, +1 fading up
static uint32_t strobeLastMs = 0;

static void replyOK()  { CTRL.println(F("OK")); }
static void replyERR(const __FlashStringHelper *msg) { CTRL.print(F("ERR ")); CTRL.println(msg); }

static bool readLine(Stream &s) {
  while (s.available()) {
    char c = (char)s.read();
    if (c == '\r') continue; // ignore CR
    if (c == '\n') {
      lineBuf[linePos] = '\0';
      linePos = 0;
      return true;
    }
    if (linePos < sizeof(lineBuf) - 1) {
      lineBuf[linePos++] = c;
    } else {
      linePos = 0;
      replyERR(F("line too long"));
    }
  }
  return false;
}

static bool parseUInt(const char *tok, uint16_t &out) {
  if (!tok || !*tok) return false;
  char *endp = nullptr;
  long v = strtol(tok, &endp, 10);
  if (*endp != '\0' || v < 0 || v > 65535) return false;
  out = (uint16_t)v;
  return true;
}

static bool parseByte(const char *tok, uint8_t &out) {
  uint16_t tmp;
  if (!parseUInt(tok, tmp) || tmp > 255) return false;
  out = (uint8_t)tmp;
  return true;
}

static void doDump() {
  // Pause strobe during dump to reduce interference
  bool wasStrobe = strobeEnabled;
  strobeEnabled = false;
  FastLED.setBrightness(brightness);

  CTRL.print(F("DUMP BEGIN "));
  CTRL.print(NUM_LEDS);
  CTRL.print(' ');
  CTRL.println(brightness);

  for (uint16_t i = 0; i < NUM_LEDS; i++) {
    CTRL.print(i);
    CTRL.print(' ');
    CTRL.print(leds[i].r);
    CTRL.print(' ');
    CTRL.print(leds[i].g);
    CTRL.print(' ');
    CTRL.println(leds[i].b);
  }

  CTRL.println(F("DUMP END"));
  replyOK();

  // Restore strobe if it was on
  if (wasStrobe) {
    strobeEnabled = true;
    strobeCur = brightness;
    strobeDir = -1;
    strobeLastMs = millis();
  }
}

static void startStrobe(uint16_t stepMs, uint8_t minBri) {
  strobeEnabled = true;
  strobeStepMs = (stepMs == 0) ? 1 : stepMs;
  strobeMin = minBri;
  strobeCur = brightness;   // start from current “normal” brightness
  strobeDir = -1;           // fade down first
  strobeLastMs = millis();
  replyOK();
}

static void stopStrobe() {
  strobeEnabled = false;
  FastLED.setBrightness(brightness);
  FastLED.show();
  replyOK();
}

static void handleCommand(char *line) {
  const char *delim = " \t";
  char *cmd = strtok(line, delim);
  if (!cmd) return;

  // ----- SET idx r g b -----
  if (!strcmp(cmd, "SET")) {
    char *tIdx = strtok(nullptr, delim);
    char *tR   = strtok(nullptr, delim);
    char *tG   = strtok(nullptr, delim);
    char *tB   = strtok(nullptr, delim);

    uint16_t idx; uint8_t r,g,b;
    if (!parseUInt(tIdx, idx) || idx >= NUM_LEDS) { replyERR(F("bad idx")); return; }
    if (!parseByte(tR, r) || !parseByte(tG, g) || !parseByte(tB, b)) { replyERR(F("bad rgb")); return; }

    leds[idx].setRGB(r, g, b);

    if (autoShow && !strobeEnabled) FastLED.show();
    replyOK();
    return;
  }

  // ----- SHOW -----
  if (!strcmp(cmd, "SHOW")) {
    FastLED.show();
    replyOK();
    return;
  }

  // ----- CLR -----
  if (!strcmp(cmd, "CLR")) {
    FastLED.clear(true); // clear + show
    replyOK();
    return;
  }

  // ----- FILL r g b -----
  if (!strcmp(cmd, "FILL")) {
    char *tR = strtok(nullptr, delim);
    char *tG = strtok(nullptr, delim);
    char *tB = strtok(nullptr, delim);
    uint8_t r,g,b;
    if (!parseByte(tR, r) || !parseByte(tG, g) || !parseByte(tB, b)) { replyERR(F("bad rgb")); return; }

    fill_solid(leds, NUM_LEDS, CRGB(r,g,b));
    if (autoShow && !strobeEnabled) FastLED.show();
    replyOK();
    return;
  }

  // ----- BRI value(0-255) -----
  if (!strcmp(cmd, "BRI")) {
    char *t = strtok(nullptr, delim);
    uint8_t b;
    if (!parseByte(t, b)) { replyERR(F("bad bri")); return; }
    brightness = b;

    // If strobing, brightness becomes the "max" level it returns to.
    if (!strobeEnabled) {
      FastLED.setBrightness(brightness);   // global brightness control :contentReference[oaicite:2]{index=2}
      FastLED.show();
    }
    replyOK();
    return;
  }

  // ----- AUTO 0/1 -----
  if (!strcmp(cmd, "AUTO")) {
    char *t = strtok(nullptr, delim);
    uint16_t v;
    if (!parseUInt(t, v) || (v != 0 && v != 1)) { replyERR(F("bad auto")); return; }
    autoShow = (v == 1);
    replyOK();
    return;
  }

  // ----- DUMP -----
  if (!strcmp(cmd, "DUMP")) {
    doDump();
    return;
  }

  // ----- STROBE 0|1 [step_ms] [min_bri] -----
  if (!strcmp(cmd, "STROBE")) {
    char *tOn = strtok(nullptr, delim);
    uint16_t on;
    if (!parseUInt(tOn, on) || (on != 0 && on != 1)) { replyERR(F("bad strobe")); return; }

    if (on == 0) { stopStrobe(); return; }

    // defaults
    uint16_t stepMs = 10;
    uint8_t minBri = 0;

    char *tStep = strtok(nullptr, delim);
    char *tMin  = strtok(nullptr, delim);

    if (tStep) {
      if (!parseUInt(tStep, stepMs)) { replyERR(F("bad step")); return; }
    }
    if (tMin) {
      if (!parseByte(tMin, minBri)) { replyERR(F("bad min")); return; }
    }
    startStrobe(stepMs, minBri);
    return;
  }

  // ----- HELP -----
  if (!strcmp(cmd, "HELP")) {
    CTRL.println(F("Commands:"));
    CTRL.println(F("  SET <idx> <r> <g> <b>"));
    CTRL.println(F("  SHOW"));
    CTRL.println(F("  CLR"));
    CTRL.println(F("  FILL <r> <g> <b>"));
    CTRL.println(F("  BRI <0-255>"));
    CTRL.println(F("  AUTO <0|1>"));
    CTRL.println(F("  DUMP"));
    CTRL.println(F("  STROBE <0|1> [step_ms] [min_bri]"));
    return;
  }

  replyERR(F("unknown cmd"));
}

void setup() {
  Serial.begin(CTRL_BAUD);

  FastLED.addLeds<NEOPIXEL, DATA_PIN>(leds, NUM_LEDS);
  FastLED.setBrightness(brightness);
  FastLED.clear(true);

  CTRL.println(F("Ready. Type HELP"));
}

void loop() {
  // Priority: process incoming commands first
  if (readLine(CTRL)) {
    handleCommand(lineBuf);
  }

  // Then run strobe animation (non-blocking)
  if (strobeEnabled) {
    uint32_t now = millis();
    if ((uint32_t)(now - strobeLastMs) >= strobeStepMs) {
      strobeLastMs = now;

      if (strobeDir < 0) {
        if (strobeCur > strobeMin) strobeCur--;
        else strobeDir = +1;
      } else {
        if (strobeCur < brightness) strobeCur++;
        else strobeDir = -1;
      }

      FastLED.setBrightness(strobeCur);
      FastLED.show();
    }
  }
}
