#include <unity.h>
#include <string.h>
#include "usage.h"

void setUp() {}
void tearDown() {}

static void expectTokens(double n, const char *want) {
  char buf[16];
  formatTokens(n, buf, sizeof(buf));
  TEST_ASSERT_EQUAL_STRING(want, buf);
}

void test_tokens_format() {
  expectTokens(-5, "0");
  expectTokens(0, "0");
  expectTokens(812, "812");
  expectTokens(1000, "1.0k");
  expectTokens(45234, "45.2k");
  expectTokens(245000, "245k");
  expectTokens(999999, "999k");
  expectTokens(1200000, "1.2M");
  expectTokens(12400000, "12.4M");
  expectTokens(3400000000.0, "3.4B");
}

void test_tokens_never_overflow_small_buffer() {
  char buf[4];
  formatTokens(1234567, buf, sizeof(buf));
  TEST_ASSERT_EQUAL(3, strlen(buf));
  formatTokens(5, nullptr, 0);   // must not touch the buffer
}

static bool parse(const char *json, UsageSlot &c, bool &hc, UsageSlot &x, bool &hx,
                  const char **err);

static void expectUsd(double n, const char *want) {
  char buf[16];
  formatUsd(n, buf, sizeof(buf));
  TEST_ASSERT_EQUAL_STRING(want, buf);
}

void test_usd_format() {
  expectUsd(-1, "$0");
  expectUsd(0, "$0");
  expectUsd(0.004, "$0");
  expectUsd(0.42, "$0.42");
  expectUsd(12.345, "$12.34");
  expectUsd(99.999, "$99.99");
  expectUsd(123.46, "$123.4");
  expectUsd(1234.9, "$1234");
  expectUsd(12345, "$12.3k");
}

void test_parse_usd() {
  UsageSlot c = {}, x = {}; bool hc, hx; const char *err;
  TEST_ASSERT_TRUE(parse("{\"claude\":{\"today\":1,\"week\":2,\"today_usd\":4.21,\"week_usd\":18.9}}",
                         c, hc, x, hx, &err));
  TEST_ASSERT_EQUAL_FLOAT(4.21f, c.todayUsd);
  TEST_ASSERT_EQUAL_FLOAT(18.9f, c.weekUsd);
  TEST_ASSERT_TRUE(parse("{\"claude\":{\"today\":1,\"week\":2}}", c, hc, x, hx, &err));
  TEST_ASSERT_EQUAL_FLOAT(-1, c.todayUsd);
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":1,\"week\":2,\"today_usd\":-1}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":1,\"week\":2,\"week_usd\":\"9\"}}", c, hc, x, hx, &err));
}

void test_status_parse() {
  uint8_t st = 99; const char *err;
  JsonDocument doc;
  deserializeJson(doc, "{\"state\":\"Busy\"}");
  TEST_ASSERT_TRUE(statusParse(doc.as<JsonVariantConst>(), st, &err));
  TEST_ASSERT_EQUAL(STATUS_BUSY, st);
  deserializeJson(doc, "{\"state\":\"IN A MEETING\"}");
  TEST_ASSERT_TRUE(statusParse(doc.as<JsonVariantConst>(), st, &err));
  TEST_ASSERT_EQUAL(STATUS_MEETING, st);
  deserializeJson(doc, "{\"state\":\"meeting\"}");
  TEST_ASSERT_TRUE(statusParse(doc.as<JsonVariantConst>(), st, &err));
  TEST_ASSERT_EQUAL(STATUS_MEETING, st);
  deserializeJson(doc, "{\"state\":\"free\"}");
  TEST_ASSERT_TRUE(statusParse(doc.as<JsonVariantConst>(), st, &err));
  TEST_ASSERT_EQUAL(STATUS_FREE, st);
}

void test_status_parse_rejects_without_changing_state() {
  uint8_t st = STATUS_BUSY; const char *err;
  const char *bad[] = {"{}", "{\"state\":5}", "{\"state\":\"away\"}", "{\"state\":\"busybusybusybusybusy\"}", "[1]"};
  for (const char *j : bad) {
    JsonDocument doc;
    deserializeJson(doc, j);
    TEST_ASSERT_FALSE(statusParse(doc.as<JsonVariantConst>(), st, &err));
    TEST_ASSERT_EQUAL(STATUS_BUSY, st);
  }
}

void test_status_labels() {
  TEST_ASSERT_EQUAL_STRING("FREE", statusLabel(STATUS_FREE));
  TEST_ASSERT_EQUAL_STRING("BUSY", statusLabel(STATUS_BUSY));
  TEST_ASSERT_EQUAL_STRING("IN A MEETING", statusLabel(STATUS_MEETING));
  TEST_ASSERT_EQUAL_STRING("", statusLabel(STATUS_COUNT));
}

void test_parse_month() {
  UsageSlot c = {}, x = {}; bool hc, hx; const char *err;
  TEST_ASSERT_TRUE(parse("{\"codex\":{\"today\":1,\"week\":2,\"month_usd\":348.9,\"month_limit_usd\":400}}",
                         c, hc, x, hx, &err));
  TEST_ASSERT_EQUAL_FLOAT(348.9f, x.monthUsd);
  TEST_ASSERT_EQUAL_FLOAT(400, x.monthLimitUsd);
  TEST_ASSERT_TRUE(parse("{\"codex\":{\"today\":1,\"week\":2}}", c, hc, x, hx, &err));
  TEST_ASSERT_EQUAL_FLOAT(-1, x.monthUsd);
  TEST_ASSERT_EQUAL_FLOAT(-1, x.monthLimitUsd);
  // A limit under $1 would divide into nonsense percentages.
  TEST_ASSERT_FALSE(parse("{\"codex\":{\"today\":1,\"week\":2,\"month_limit_usd\":0}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"codex\":{\"today\":1,\"week\":2,\"month_usd\":-5}}", c, hc, x, hx, &err));
}

void test_reset_format() {
  char b[16];
  formatReset(5, b, sizeof(b));    TEST_ASSERT_EQUAL_STRING("5 m", b);
  formatReset(134, b, sizeof(b));  TEST_ASSERT_EQUAL_STRING("2 h 14 m", b);
  formatReset(3 * 1440 + 4 * 60, b, sizeof(b)); TEST_ASSERT_EQUAL_STRING("3 d 4 h", b);
  formatReset(-1, b, sizeof(b));   TEST_ASSERT_EQUAL_STRING("", b);
}

static bool parse(const char *json, UsageSlot &c, bool &hc, UsageSlot &x, bool &hx,
                  const char **err) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) { *err = "json"; return false; }
  return usageParse(doc.as<JsonVariantConst>(), c, hc, x, hx, err);
}

void test_parse_both() {
  UsageSlot c = {}, x = {}; bool hc, hx; const char *err;
  TEST_ASSERT_TRUE(parse("{\"claude\":{\"today\":100,\"week\":700,\"pct1\":42,\"reset1\":134},"
                         "\"codex\":{\"today\":5,\"week\":6}}", c, hc, x, hx, &err));
  TEST_ASSERT_TRUE(hc); TEST_ASSERT_TRUE(hx);
  TEST_ASSERT_TRUE(c.valid);
  TEST_ASSERT_EQUAL_FLOAT(100, c.today);
  TEST_ASSERT_EQUAL(42, c.pct1);
  TEST_ASSERT_EQUAL(-1, c.pct2);
  TEST_ASSERT_EQUAL(134, c.reset1);
  TEST_ASSERT_EQUAL(-1, x.pct1);
  TEST_ASSERT_EQUAL(-1, x.reset1);
}

void test_parse_one_provider_leaves_other() {
  UsageSlot c = {}, x = {}; bool hc, hx; const char *err;
  x.today = 9;
  TEST_ASSERT_TRUE(parse("{\"codex\":{\"today\":1,\"week\":2}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(hc); TEST_ASSERT_TRUE(hx);
  TEST_ASSERT_FALSE(c.valid);
  TEST_ASSERT_EQUAL_FLOAT(1, x.today);
}

void test_parse_rejects_bad_input_without_touching_outputs() {
  UsageSlot c = {}, x = {}; bool hc, hx; const char *err;
  x.today = 9; x.valid = true;
  // codex is valid but claude is not: nothing may be stored.
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":-1,\"week\":2},\"codex\":{\"today\":1,\"week\":2}}",
                          c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(hc); TEST_ASSERT_FALSE(hx);
  TEST_ASSERT_EQUAL_FLOAT(9, x.today);
  TEST_ASSERT_FALSE(parse("{}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("[1]", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":\"5\",\"week\":2}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":1,\"week\":2,\"pct1\":101}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"claude\":{\"today\":1,\"week\":2,\"reset1\":-3}}", c, hc, x, hx, &err));
  TEST_ASSERT_FALSE(parse("{\"claude\":5}", c, hc, x, hx, &err));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_tokens_format);
  RUN_TEST(test_tokens_never_overflow_small_buffer);
  RUN_TEST(test_usd_format);
  RUN_TEST(test_parse_usd);
  RUN_TEST(test_status_parse);
  RUN_TEST(test_status_parse_rejects_without_changing_state);
  RUN_TEST(test_status_labels);
  RUN_TEST(test_parse_month);
  RUN_TEST(test_reset_format);
  RUN_TEST(test_parse_both);
  RUN_TEST(test_parse_one_provider_leaves_other);
  RUN_TEST(test_parse_rejects_bad_input_without_touching_outputs);
  return UNITY_END();
}
