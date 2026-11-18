#include <unity.h>
#include <string.h>
#include "feed.h"

void setUp() {}
void tearDown() {}

static JsonDocument doc;
static JsonVariantConst json(const char *text) {
  doc.clear();
  deserializeJson(doc, text);
  return doc.as<JsonVariantConst>();
}

void test_weather_ok_and_defaults() {
  FeedWeather w = {}; const char *err = "";
  TEST_ASSERT_TRUE(feedWeatherParse(json("{\"temp\":31.4,\"code\":1}"), w, &err));
  TEST_ASSERT_EQUAL(31, w.temp);
  TEST_ASSERT_EQUAL(0, w.humidity);
  TEST_ASSERT_TRUE(w.isDay);
  TEST_ASSERT_TRUE(feedWeatherParse(json("{\"temp\":-5,\"humidity\":70,\"wind\":9,\"code\":95,\"is_day\":false}"), w, &err));
  TEST_ASSERT_EQUAL(-5, w.temp);
  TEST_ASSERT_EQUAL(70, w.humidity);
  TEST_ASSERT_EQUAL(95, w.code);
  TEST_ASSERT_FALSE(w.isDay);
}

void test_weather_rejects_without_touching_output() {
  FeedWeather w = {}; w.temp = 7; const char *err = "";
  TEST_ASSERT_FALSE(feedWeatherParse(json("{\"code\":1}"), w, &err));
  TEST_ASSERT_FALSE(feedWeatherParse(json("{\"temp\":\"hot\",\"code\":1}"), w, &err));
  TEST_ASSERT_FALSE(feedWeatherParse(json("{\"temp\":20,\"code\":100}"), w, &err));
  TEST_ASSERT_FALSE(feedWeatherParse(json("{\"temp\":20,\"code\":1,\"humidity\":101}"), w, &err));
  TEST_ASSERT_FALSE(feedWeatherParse(json("{\"temp\":20,\"code\":1,\"is_day\":\"yes\"}"), w, &err));
  TEST_ASSERT_FALSE(feedWeatherParse(json("[1]"), w, &err));
  TEST_ASSERT_EQUAL(7, w.temp);
}

void test_stock() {
  FeedStock s = {}; const char *err = "";
  TEST_ASSERT_TRUE(feedStockParse(json("{\"price\":327.74}"), s, &err));
  TEST_ASSERT_EQUAL_FLOAT(327.74f, s.price);
  TEST_ASSERT_EQUAL_FLOAT(327.74f, s.high);          // missing open/high/low follow the price
  TEST_ASSERT_EQUAL_STRING("", s.symbol);
  TEST_ASSERT_TRUE(feedStockParse(json("{\"symbol\":\"brk-b\",\"price\":400,\"open\":399,\"high\":405,\"low\":398}"), s, &err));
  TEST_ASSERT_EQUAL_STRING("BRK-B", s.symbol);
  TEST_ASSERT_EQUAL_FLOAT(405, s.high);
}

void test_stock_rejects() {
  FeedStock s = {}; s.price = 1; const char *err = "";
  TEST_ASSERT_FALSE(feedStockParse(json("{\"price\":0}"), s, &err));
  TEST_ASSERT_FALSE(feedStockParse(json("{}"), s, &err));
  TEST_ASSERT_FALSE(feedStockParse(json("{\"price\":5,\"symbol\":\"TOOLONGSYMBOLX\"}"), s, &err));
  TEST_ASSERT_FALSE(feedStockParse(json("{\"price\":5,\"symbol\":\"A B\"}"), s, &err));
  TEST_ASSERT_FALSE(feedStockParse(json("{\"price\":5,\"symbol\":7}"), s, &err));
  TEST_ASSERT_FALSE(feedStockParse(json("{\"price\":5,\"open\":-1}"), s, &err));
  TEST_ASSERT_EQUAL_FLOAT(1, s.price);
}

void test_github() {
  FeedGithub g = {}; const char *err = "";
  TEST_ASSERT_TRUE(feedGithubParse(json("{\"followers\":1234,\"repos\":56}"), g, &err));
  TEST_ASSERT_EQUAL(1234, g.followers);
  TEST_ASSERT_EQUAL(56, g.repos);
  TEST_ASSERT_FALSE(feedGithubParse(json("{\"followers\":1}"), g, &err));
  TEST_ASSERT_FALSE(feedGithubParse(json("{\"followers\":-1,\"repos\":1}"), g, &err));
  TEST_ASSERT_EQUAL(1234, g.followers);
}

void test_time() {
  uint32_t e = 5; const char *err = "";
  TEST_ASSERT_TRUE(feedTimeParse(json("{\"epoch\":1790000000}"), e, &err));
  TEST_ASSERT_EQUAL_UINT32(1790000000UL, e);
  TEST_ASSERT_FALSE(feedTimeParse(json("{\"epoch\":12345}"), e, &err));      // 1970: clock never set
  TEST_ASSERT_FALSE(feedTimeParse(json("{\"epoch\":9999999999}"), e, &err));
  TEST_ASSERT_FALSE(feedTimeParse(json("{\"epoch\":\"1790000000\"}"), e, &err));
  TEST_ASSERT_FALSE(feedTimeParse(json("{}"), e, &err));
  TEST_ASSERT_EQUAL_UINT32(1790000000UL, e);
}

void test_agent() {
  FeedAgent a = {}; const char *err = "";
  TEST_ASSERT_TRUE(feedAgentParse(json("{\"show\":true}"), a, &err));
  TEST_ASSERT_TRUE(a.hasShow && a.show);
  TEST_ASSERT_FALSE(a.hasText);
  TEST_ASSERT_TRUE(feedAgentParse(json("{\"show\":false,\"text\":\"DON'T TOUCH my laptop\"}"), a, &err));
  TEST_ASSERT_FALSE(a.show);
  TEST_ASSERT_TRUE(a.hasText);
  TEST_ASSERT_EQUAL_STRING("DON'T TOUCH my laptop", a.text);
  TEST_ASSERT_TRUE(feedAgentParse(json("{\"text\":\"\"}"), a, &err));   // "" = back to the default
  TEST_ASSERT_TRUE(a.hasText);
  TEST_ASSERT_EQUAL_STRING("", a.text);
  TEST_ASSERT_TRUE(feedAgentParse(json("{\"text\":\"123456789012345678901234\"}"), a, &err));   // 24: fits
  TEST_ASSERT_TRUE(feedAgentParse(json("{\"pin\":true}"), a, &err));
  TEST_ASSERT_TRUE(a.hasPin && a.pin);
  TEST_ASSERT_FALSE(a.hasShow);
}

void test_agent_rejects() {
  FeedAgent a = {}; a.hasShow = true; const char *err = "";
  TEST_ASSERT_FALSE(feedAgentParse(json("{}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"show\":\"yes\"}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"pin\":1}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"text\":\"1234567890123456789012345\"}"), a, &err));   // 25
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"text\":\"   \"}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"text\":\"caf\\u00e9\"}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("{\"text\":5}"), a, &err));
  TEST_ASSERT_FALSE(feedAgentParse(json("[true]"), a, &err));
  TEST_ASSERT_TRUE(a.hasShow);                       // untouched
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_weather_ok_and_defaults);
  RUN_TEST(test_weather_rejects_without_touching_output);
  RUN_TEST(test_stock);
  RUN_TEST(test_stock_rejects);
  RUN_TEST(test_github);
  RUN_TEST(test_time);
  RUN_TEST(test_agent);
  RUN_TEST(test_agent_rejects);
  return UNITY_END();
}
