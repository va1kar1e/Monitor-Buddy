#include "jiggle.h"

#include <math.h>
#include <string.h>
#include <strings.h>

namespace {

bool wholeNumber(JsonVariantConst v, double lo, double hi, double &out) {
  if (!v.is<double>() && !v.is<long>()) return false;
  double d = v.as<double>();
  if (isnan(d) || d < lo || d > hi || d != floor(d)) return false;
  out = d;
  return true;
}

}  // namespace

bool jiggleParse(JsonVariantConst body, JiggleConfig &cfg, const char **error) {
  if (!body.is<JsonObjectConst>()) { *error = "body must be a JSON object"; return false; }
  JiggleConfig next = cfg;
  JsonVariantConst on = body["enabled"];
  if (!on.isNull()) {
    if (!on.is<bool>()) { *error = "enabled must be true or false"; return false; }
    next.enabled = on.as<bool>();
  }
  JsonVariantConst mode = body["mode"];
  if (!mode.isNull()) {
    const char *m = mode.is<const char *>() ? mode.as<const char *>() : nullptr;
    if (m && !strcasecmp(m, "steady"))      next.mode = JIGGLE_STEADY;
    else if (m && !strcasecmp(m, "random")) next.mode = JIGGLE_RANDOM;
    else { *error = "mode must be steady or random"; return false; }
  }
  double v;
  if (!body["interval"].isNull()) {
    if (!wholeNumber(body["interval"], 1, 3600, v)) { *error = "interval is 1-3600 seconds"; return false; }
    next.intervalS = (uint16_t)v;
  }
  if (!body["distance"].isNull()) {
    if (!wholeNumber(body["distance"], 1, 50, v)) { *error = "distance is 1-50 pixels"; return false; }
    next.distance = (uint8_t)v;
  }
  cfg = next;
  return true;
}

const char *jiggleModeName(uint8_t mode) { return mode == JIGGLE_STEADY ? "steady" : "random"; }

JiggleMove jiggleMove(const JiggleConfig &cfg, bool &flip, uint32_t rndA, uint32_t rndB) {
  const int d = cfg.distance < 1 ? 1 : cfg.distance > 50 ? 50 : cfg.distance;
  if (cfg.mode == JIGGLE_STEADY) {
    flip = !flip;
    return {(int8_t)(flip ? d : -d), 0};
  }
  int dx = (int)(rndA % (2u * d + 1)) - d;
  int dy = (int)(rndB % (2u * d + 1)) - d;
  if (dx == 0 && dy == 0) dx = 1;
  return {(int8_t)dx, (int8_t)dy};
}

uint32_t jiggleDelayMs(const JiggleConfig &cfg, uint32_t rnd) {
  const uint32_t base = (uint32_t)(cfg.intervalS < 1 ? 1 : cfg.intervalS) * 1000UL;
  if (cfg.mode == JIGGLE_STEADY) return base;
  return base / 2 + rnd % (base + 1);
}
