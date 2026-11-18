#include <unity.h>
#include "jiggle.h"

void setUp() {}
void tearDown() {}

static JsonDocument doc;
static JsonVariantConst json(const char *t) { doc.clear(); deserializeJson(doc, t); return doc.as<JsonVariantConst>(); }

void test_partial_update() {
  JiggleConfig c = JIGGLE_DEFAULT; const char *err = "";
  TEST_ASSERT_TRUE(jiggleParse(json("{\"enabled\":true}"), c, &err));
  TEST_ASSERT_TRUE(c.enabled);
  TEST_ASSERT_EQUAL(JIGGLE_RANDOM, c.mode);
  TEST_ASSERT_EQUAL(30, c.intervalS);
  TEST_ASSERT_TRUE(jiggleParse(json("{\"mode\":\"STEADY\",\"interval\":10,\"distance\":8}"), c, &err));
  TEST_ASSERT_EQUAL(JIGGLE_STEADY, c.mode);
  TEST_ASSERT_EQUAL(10, c.intervalS);
  TEST_ASSERT_EQUAL(8, c.distance);
  TEST_ASSERT_TRUE(c.enabled);
}

void test_bad_input_changes_nothing() {
  JiggleConfig c = JIGGLE_DEFAULT; const char *err = "";
  TEST_ASSERT_FALSE(jiggleParse(json("{\"enabled\":true,\"interval\":0}"), c, &err));
  TEST_ASSERT_FALSE(c.enabled);                      // the valid key was not applied either
  TEST_ASSERT_FALSE(jiggleParse(json("{\"interval\":3601}"), c, &err));
  TEST_ASSERT_FALSE(jiggleParse(json("{\"interval\":2.5}"), c, &err));
  TEST_ASSERT_FALSE(jiggleParse(json("{\"distance\":51}"), c, &err));
  TEST_ASSERT_FALSE(jiggleParse(json("{\"mode\":\"wild\"}"), c, &err));
  TEST_ASSERT_FALSE(jiggleParse(json("{\"enabled\":\"yes\"}"), c, &err));
  TEST_ASSERT_FALSE(jiggleParse(json("[1]"), c, &err));
  TEST_ASSERT_EQUAL(30, c.intervalS);
}

void test_steady_alternates() {
  JiggleConfig c = JIGGLE_DEFAULT; c.mode = JIGGLE_STEADY; c.distance = 6;
  bool flip = false;
  JiggleMove a = jiggleMove(c, flip, 0, 0), b = jiggleMove(c, flip, 0, 0);
  TEST_ASSERT_EQUAL(6, a.dx);
  TEST_ASSERT_EQUAL(-6, b.dx);
  TEST_ASSERT_EQUAL(0, a.dy);
}

void test_random_stays_within_distance_and_never_zero() {
  JiggleConfig c = JIGGLE_DEFAULT; c.distance = 4;
  bool flip = false;
  for (uint32_t i = 0; i < 500; i++) {
    JiggleMove m = jiggleMove(c, flip, i * 2654435761u, i * 40503u + 7);
    TEST_ASSERT_TRUE(m.dx >= -4 && m.dx <= 4 && m.dy >= -4 && m.dy <= 4);
    TEST_ASSERT_FALSE(m.dx == 0 && m.dy == 0);
  }
}

void test_delay() {
  JiggleConfig c = JIGGLE_DEFAULT; c.intervalS = 20;
  c.mode = JIGGLE_STEADY;
  TEST_ASSERT_EQUAL_UINT32(20000, jiggleDelayMs(c, 12345));
  c.mode = JIGGLE_RANDOM;
  for (uint32_t i = 0; i < 300; i++) {
    uint32_t d = jiggleDelayMs(c, i * 2654435761u);
    TEST_ASSERT_TRUE(d >= 10000 && d <= 30000);
  }
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_partial_update);
  RUN_TEST(test_bad_input_changes_nothing);
  RUN_TEST(test_steady_alternates);
  RUN_TEST(test_random_stays_within_distance_and_never_zero);
  RUN_TEST(test_delay);
  return UNITY_END();
}
