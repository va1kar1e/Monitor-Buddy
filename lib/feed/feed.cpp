#include "feed.h"

#include <ctype.h>
#include <math.h>
#include <string.h>

namespace {

bool number(JsonVariantConst v, double lo, double hi, double &out) {
  if (!v.is<double>() && !v.is<long>()) return false;
  double d = v.as<double>();
  if (isnan(d) || d < lo || d > hi) return false;
  out = d;
  return true;
}

// Absent gives `fallback`; present but out of range is an error.
bool optionalNumber(JsonVariantConst obj, const char *key, double lo, double hi, double fallback, double &out) {
  JsonVariantConst v = obj[key];
  if (v.isNull()) { out = fallback; return true; }
  return number(v, lo, hi, out);
}

bool isObject(JsonVariantConst body, const char **error) {
  if (body.is<JsonObjectConst>()) return true;
  *error = "body must be a JSON object";
  return false;
}

}  // namespace

bool feedWeatherParse(JsonVariantConst body, FeedWeather &out, const char **error) {
  if (!isObject(body, error)) return false;
  double temp, hum, wind, code;
  if (!number(body["temp"], -100, 200, temp)) { *error = "temp must be a number from -100 to 200"; return false; }
  if (!optionalNumber(body, "humidity", 0, 100, 0, hum)) { *error = "humidity is 0-100"; return false; }
  if (!optionalNumber(body, "wind", 0, 500, 0, wind)) { *error = "wind is 0-500"; return false; }
  if (!number(body["code"], 0, 99, code)) { *error = "code must be a weather code 0-99"; return false; }
  JsonVariantConst day = body["is_day"];
  if (!day.isNull() && !day.is<bool>()) { *error = "is_day must be true or false"; return false; }
  out.temp     = (int16_t)lround(temp);
  out.humidity = (int16_t)lround(hum);
  out.wind     = (int16_t)lround(wind);
  out.code     = (int16_t)lround(code);
  out.isDay    = day.isNull() ? true : day.as<bool>();
  return true;
}

bool feedStockParse(JsonVariantConst body, FeedStock &out, const char **error) {
  if (!isObject(body, error)) return false;
  double price, open, high, low;
  if (!number(body["price"], 0, 1e7, price) || price <= 0) { *error = "price must be a number above 0"; return false; }
  if (!optionalNumber(body, "open", 0, 1e7, price, open) || !optionalNumber(body, "high", 0, 1e7, price, high) ||
      !optionalNumber(body, "low", 0, 1e7, price, low)) {
    *error = "open, high and low are 0-10000000";
    return false;
  }
  char symbol[12] = "";
  JsonVariantConst s = body["symbol"];
  if (!s.isNull()) {
    const char *raw = s.is<const char *>() ? s.as<const char *>() : nullptr;
    size_t n = raw ? strlen(raw) : 0;
    bool ok = raw && n >= 1 && n < sizeof(symbol);
    for (size_t i = 0; ok && i < n; i++) {
      char c = (char)toupper((unsigned char)raw[i]);
      ok = isalnum((unsigned char)c) || c == '.' || c == '-' || c == '^';
      symbol[i] = c;
    }
    if (!ok) { *error = "symbol is 1-11 letters, digits, . - ^"; return false; }
    symbol[n] = '\0';
  }
  out.price = (float)price;
  out.open  = (float)open;
  out.high  = (float)high;
  out.low   = (float)low;
  strcpy(out.symbol, symbol);
  return true;
}

bool feedGithubParse(JsonVariantConst body, FeedGithub &out, const char **error) {
  if (!isObject(body, error)) return false;
  double followers, repos;
  if (!number(body["followers"], 0, 1e9, followers) || !number(body["repos"], 0, 1e9, repos)) {
    *error = "followers and repos must be numbers >= 0";
    return false;
  }
  out.followers = (int32_t)followers;
  out.repos     = (int32_t)repos;
  return true;
}

bool feedTimeParse(JsonVariantConst body, uint32_t &epoch, const char **error) {
  if (!isObject(body, error)) return false;
  double e;
  if (!number(body["epoch"], 1700000000.0, 4102444800.0, e)) {
    *error = "epoch must be seconds since 1970, from 1700000000 to 4102444800";
    return false;
  }
  epoch = (uint32_t)e;
  return true;
}

bool feedAgentParse(JsonVariantConst body, FeedAgent &out, const char **error) {
  if (!isObject(body, error)) return false;
  FeedAgent next = {};
  JsonVariantConst show = body["show"];
  if (!show.isNull()) {
    if (!show.is<bool>()) { *error = "show must be true or false"; return false; }
    next.hasShow = true;
    next.show = show.as<bool>();
  }
  JsonVariantConst pin = body["pin"];
  if (!pin.isNull()) {
    if (!pin.is<bool>()) { *error = "pin must be true or false"; return false; }
    next.hasPin = true;
    next.pin = pin.as<bool>();
  }
  JsonVariantConst text = body["text"];
  if (!text.isNull()) {
    const char *t = text.is<const char *>() ? text.as<const char *>() : nullptr;
    const size_t n = t ? strlen(t) : 0;
    bool ok = t && n < sizeof(next.text);
    bool blank = true;
    for (size_t i = 0; ok && i < n; i++) {
      const unsigned char ch = (unsigned char)t[i];
      ok = ch >= 0x20 && ch <= 0x7E;
      if (ch != ' ') blank = false;
    }
    if (!ok || (n > 0 && blank)) { *error = "text is 1-24 letters, digits and punctuation (no accents or emoji)"; return false; }
    next.hasText = true;
    memcpy(next.text, t, n);
    next.text[n] = '\0';
  }
  if (!next.hasShow && !next.hasPin && !next.hasText) { *error = "give show, pin and/or text"; return false; }
  out = next;
  return true;
}
