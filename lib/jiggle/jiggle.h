#pragma once
// The Buddy's own mouse jiggler: on the HID firmware (env esp32-s3-hid) the Buddy shows up
// to the computer as a USB mouse and nudges the pointer now and then, so the computer
// does not go idle, with no software running on it. This is the pure part (settings,
// parsing, the moves and the timing); main.cpp owns the USB mouse and the clock.
// No Arduino types, so it is unit-tested on the PC (pio test -e native).
#include <ArduinoJson.h>
#include <stdint.h>

enum JiggleMode : uint8_t { JIGGLE_STEADY = 0, JIGGLE_RANDOM = 1 };

struct JiggleConfig {
  bool     enabled;
  uint8_t  mode;        // JiggleMode
  uint16_t intervalS;   // 1-3600 seconds
  uint8_t  distance;    // 1-50 pixels
};

static const JiggleConfig JIGGLE_DEFAULT = {false, JIGGLE_RANDOM, 30, 5};

// JIGGLE {"enabled": true, "mode": "random" | "steady", "interval": 30, "distance": 5}
// Every key is optional and only the ones present change. A bad value fails the whole
// request and leaves cfg untouched; *error says why.
bool jiggleParse(JsonVariantConst body, JiggleConfig &cfg, const char **error);

const char *jiggleModeName(uint8_t mode);   // "steady" / "random"

struct JiggleMove { int8_t dx, dy; };

// One nudge, out; the caller moves back by (-dx, -dy) a moment later. Steady goes
// right, then left, then right again (`flip` keeps the turn); random picks a spot within
// `distance` of where the pointer is, from two random numbers.
JiggleMove jiggleMove(const JiggleConfig &cfg, bool &flip, uint32_t rndA, uint32_t rndB);

// Milliseconds until the next nudge: steady is the interval, random is 0.5 to 1.5 times it.
uint32_t jiggleDelayMs(const JiggleConfig &cfg, uint32_t rnd);
