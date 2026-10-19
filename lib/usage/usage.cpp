#include "usage.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace {

bool readNumber(JsonVariantConst v, double minV, double maxV, double &out) {
  if (!v.is<double>() && !v.is<long>()) return false;
  double d = v.as<double>();
  if (isnan(d) || d < minV || d > maxV) return false;
  out = d;
  return true;
}

// -1 when the key is absent, false when present but out of range.
bool readOptional(JsonVariantConst obj, const char *key, double maxV, long &out) {
  out = -1;
  JsonVariantConst v = obj[key];
  if (v.isNull()) return true;
  double d;
  if (!readNumber(v, 0, maxV, d)) return false;
  out = (long)d;
  return true;
}

// -1 when the key is absent, false when present but out of range.
bool readOptionalFloat(JsonVariantConst obj, const char *key, double maxV, float &out) {
  out = -1;
  JsonVariantConst v = obj[key];
  if (v.isNull()) return true;
  double d;
  if (!readNumber(v, 0, maxV, d)) return false;
  out = (float)d;
  return true;
}

bool parseSlot(JsonVariantConst obj, UsageSlot &slot, const char **error,
               const char *name) {
  static char msg[48];
  if (!obj.is<JsonObjectConst>()) {
    snprintf(msg, sizeof(msg), "%s must be an object", name);
    *error = msg;
    return false;
  }
  double today, week;
  if (!readNumber(obj["today"], 0, 1e13, today) || !readNumber(obj["week"], 0, 1e13, week)) {
    snprintf(msg, sizeof(msg), "%s: today and week must be numbers >= 0", name);
    *error = msg;
    return false;
  }
  long p1, p2, r1;
  if (!readOptional(obj, "pct1", 100, p1) || !readOptional(obj, "pct2", 100, p2) ||
      !readOptional(obj, "reset1", 1e6, r1)) {
    snprintf(msg, sizeof(msg), "%s: pct1/pct2 are 0-100, reset1 >= 0", name);
    *error = msg;
    return false;
  }
  float tu, wu;
  if (!readOptionalFloat(obj, "today_usd", 1e7, tu) || !readOptionalFloat(obj, "week_usd", 1e7, wu)) {
    snprintf(msg, sizeof(msg), "%s: today_usd/week_usd are 0-10000000", name);
    *error = msg;
    return false;
  }
  float mu, ml;
  if (!readOptionalFloat(obj, "month_usd", 1e7, mu) || !readOptionalFloat(obj, "month_limit_usd", 1e7, ml) ||
      (ml != -1 && ml < 1)) {
    snprintf(msg, sizeof(msg), "%s: month_usd 0+, month_limit_usd 1+", name);
    *error = msg;
    return false;
  }
  slot.todayUsd = tu;
  slot.weekUsd  = wu;
  slot.monthUsd = mu;
  slot.monthLimitUsd = ml;
  slot.valid = true;
  slot.today = (float)today;
  slot.week  = (float)week;
  slot.pct1  = (int16_t)p1;
  slot.pct2  = (int16_t)p2;
  slot.reset1 = (int32_t)r1;
  return true;
}

}  // namespace

bool usageParse(JsonVariantConst body, UsageSlot &claude, bool &hasClaude,
                UsageSlot &codex, bool &hasCodex, const char **error) {
  static const char *none = "";
  *error = none;
  hasClaude = hasCodex = false;
  if (!body.is<JsonObjectConst>()) { *error = "body must be a JSON object"; return false; }
  UsageSlot c = {}, x = {};
  bool gotC = !body["claude"].isNull(), gotX = !body["codex"].isNull();
  if (!gotC && !gotX) { *error = "need claude and/or codex"; return false; }
  if (gotC && !parseSlot(body["claude"], c, error, "claude")) return false;
  if (gotX && !parseSlot(body["codex"], x, error, "codex")) return false;
  if (gotC) { claude = c; hasClaude = true; }
  if (gotX) { codex = x;  hasCodex = true; }
  return true;
}

void formatTokens(double n, char *out, size_t len) {
  if (len == 0) return;
  if (isnan(n) || n < 1) { snprintf(out, len, "0"); return; }
  if (n < 1000) { snprintf(out, len, "%d", (int)n); return; }
  static const char units[] = {'k', 'M', 'B', 'T'};
  double v = n;
  int u = -1;
  do { v /= 1000; u++; } while (v >= 1000 && u < 3);
  // Truncated, never rounded up: 999999 is "999k", not "1000k".
  if (v < 100) snprintf(out, len, "%.1f%c", floor(v * 10) / 10, units[u]);
  else         snprintf(out, len, "%.0f%c", floor(v), units[u]);
}

const char *statusLabel(uint8_t state) {
  switch (state) {
    case STATUS_FREE:    return "FREE";
    case STATUS_BUSY:    return "BUSY";
    case STATUS_MEETING: return "IN A MEETING";
    default:             return "";
  }
}

bool statusParse(JsonVariantConst body, uint8_t &state, const char **error) {
  static const char *const bad = "state must be free, busy or meeting";
  if (!body.is<JsonObjectConst>()) { *error = "body must be a JSON object"; return false; }
  const char *raw = body["state"] | (const char *)nullptr;
  if (!raw) { *error = bad; return false; }
  char word[16];
  size_t n = 0;
  for (; raw[n] && n < sizeof(word) - 1; n++) word[n] = (char)tolower((unsigned char)raw[n]);
  word[n] = '\0';
  if (raw[n]) { *error = bad; return false; }   // too long to be one of the words
  if (!strcmp(word, "free"))                                           state = STATUS_FREE;
  else if (!strcmp(word, "busy"))                                      state = STATUS_BUSY;
  else if (!strcmp(word, "meeting") || !strcmp(word, "in a meeting"))  state = STATUS_MEETING;
  else { *error = bad; return false; }
  return true;
}

void formatUsd(double usd, char *out, size_t len) {
  if (len == 0) return;
  if (isnan(usd) || usd < 0.005) { snprintf(out, len, "$0"); return; }
  // Truncated, like formatTokens: 99.999 is "$99.99", never "$100.00".
  if (usd < 100)        snprintf(out, len, "$%.2f", floor(usd * 100) / 100);
  else if (usd < 1000)  snprintf(out, len, "$%.1f", floor(usd * 10) / 10);
  else if (usd < 10000) snprintf(out, len, "$%.0f", floor(usd));
  else                  snprintf(out, len, "$%.1fk", floor(usd / 100) / 10);
}

void formatReset(long minutes, char *out, size_t len) {
  if (len == 0) return;
  if (minutes < 0) { out[0] = '\0'; return; }
  if (minutes < 60)        snprintf(out, len, "%ld m", minutes);
  else if (minutes < 1440) snprintf(out, len, "%ld h %ld m", minutes / 60, minutes % 60);
  else                     snprintf(out, len, "%ld d %ld h", minutes / 1440, (minutes % 1440) / 60);
}
