#pragma once
// AI-assistant usage pushed to the Buddy by a PC (tools/usage_push.py): the
// body of POST /usage and the text helpers of the two usage pages. Pure C++ with
// no Arduino types, so it is unit-tested on the PC (pio test -e native).
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>

// One assistant's numbers. today/week are tokens (input + output, no cache
// reads); pct1/pct2 are limit usage in percent and reset1 the minutes until the
// first limit resets, all -1 when the PC has no such number.
struct UsageSlot {
  bool     valid;
  float    today, week;
  int16_t  pct1, pct2;
  int32_t  reset1;
  float    todayUsd, weekUsd;   // US dollars, -1 when the PC sent none
  uint32_t updatedAt;   // millis() of the push; set by the caller
};

// Body: {"claude": {...}, "codex": {...}}, each object optional:
//   {"today": 123456, "week": 9876543, "pct1": 42, "pct2": 17, "reset1": 134,
//    "today_usd": 4.21, "week_usd": 18.9}
// "today" and "week" are required numbers >= 0; the rest are optional (pct 0-100,
// reset1 >= 0, *_usd 0-1e7). A present provider that is invalid fails the whole body and
// leaves every output untouched. Unknown keys are ignored. At least one provider
// must be present.
bool usageParse(JsonVariantConst body, UsageSlot &claude, bool &hasClaude,
                UsageSlot &codex, bool &hasCodex, const char **error);

// "812", "45.2k", "245k", "1.2M", "12M", "3.4B". Never wider than 5 characters
// for values below 1e12. Negative or NaN gives "0". Always terminates (nothing
// if len is 0).
void formatTokens(double n, char *out, size_t len);

// "$0.42", "$12.34", "$123.4", "$1234", "$12.3k". Negative or NaN gives "$0".
void formatUsd(double usd, char *out, size_t len);

// ── Availability status: Free / Busy / In a meeting ──────────
enum StatusState : uint8_t { STATUS_FREE = 0, STATUS_BUSY = 1, STATUS_MEETING = 2, STATUS_COUNT = 3 };

// Body: {"state": "free" | "busy" | "meeting"} (also "in a meeting"; any case).
// On failure state is untouched and *error says why.
bool statusParse(JsonVariantConst body, uint8_t &state, const char **error);

// "FREE", "BUSY", "IN A MEETING"; "" for a state out of range.
const char *statusLabel(uint8_t state);

// "5 m", "2 h 14 m", "3 d 4 h" for a number of minutes (negative gives "").
void formatReset(long minutes, char *out, size_t len);
