#pragma once
// Numbers for the network pages (weather, stock, GitHub) and the clock, pushed to
// the Buddy by the desktop app over USB ("@MB WEATHER {...}" and so on). They let
// those pages work with no Wi-Fi: the PC fetches what the Buddy would have fetched.
// Pure C++ with no Arduino types, so it is unit-tested on the PC (pio test -e native).
#include <ArduinoJson.h>
#include <stdint.h>

struct FeedWeather { int16_t temp, humidity, wind, code; bool isDay; };
struct FeedStock   { float price, open, high, low; char symbol[12]; };   // symbol "" when not sent
struct FeedGithub  { int32_t followers, repos; };

// Every parser leaves its output untouched on failure and sets *error to a short text.
//
// WEATHER {"temp": 31, "humidity": 70, "wind": 9, "code": 1, "is_day": true}
//   temp -100..200 (either unit), humidity 0-100, wind 0-500, code 0-99 (WMO).
//   humidity, wind and is_day are optional (0, 0, true).
bool feedWeatherParse(JsonVariantConst body, FeedWeather &out, const char **error);

// STOCK {"symbol": "AAPL", "price": 327.74, "open": 323.1, "high": 329.6, "low": 322.2}
//   price > 0 is required; open/high/low are 0-1e7 and default to the price;
//   symbol is optional: up to 11 of A-Z 0-9 . - ^ (lower case is made upper).
bool feedStockParse(JsonVariantConst body, FeedStock &out, const char **error);

// GITHUB {"followers": 1234, "repos": 56}  both required numbers >= 0.
bool feedGithubParse(JsonVariantConst body, FeedGithub &out, const char **error);

// TIME {"epoch": 1790000000}  seconds since 1970 UTC (the Buddy applies its own
// time zone), 1700000000 to 4102444800 (year 2100).
bool feedTimeParse(JsonVariantConst body, uint32_t &epoch, const char **error);

// AGENT {"show": true | false, "pin": true | false, "text": "DON'T TOUCH my laptop"}  each optional,
// at least one.
//   show: whether the "AI agent is running" page is in the AI section.
//   pin:  stay on that page: the auto page scrolling does not move off it (a swipe still does).
//   text: the page's last line, 1-24 printable ASCII characters (the font has no more);
//         "" puts the default back, which the caller fills in (hasText true, text "").
struct FeedAgent { bool hasShow, show; bool hasPin, pin; bool hasText; char text[25]; };
bool feedAgentParse(JsonVariantConst body, FeedAgent &out, const char **error);
