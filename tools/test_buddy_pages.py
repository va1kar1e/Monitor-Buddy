import datetime as dt
import unittest

import buddy_pages as bp


class Clock(unittest.TestCase):
    def test_clock_page(self):
        t = dt.datetime(2026, 10, 19, 22, 24, 36)   # a Monday
        self.assertEqual(bp.clock_page(t), ("22:24:36", "Monday", "19 October 2026"))

    def test_day_has_no_leading_zero(self):
        self.assertEqual(bp.clock_page(dt.datetime(2026, 3, 5, 1, 2, 3))[2], "5 March 2026")


class Weather(unittest.TestCase):
    CUR = {"current": {"temperature_2m": 31.4, "relative_humidity_2m": 70, "weather_code": 61,
                       "wind_speed_10m": 9.2, "is_day": 0}}

    def test_text_for_codes_matches_the_buddy(self):
        want = {0: "CLEAR", 1: "PARTLY CLOUDY", 3: "CLOUDY", 45: "FOG", 61: "RAIN", 81: "RAIN",
                73: "SNOW", 96: "STORM", 10: "WEATHER"}
        for code, text in want.items():
            self.assertEqual(bp.weather_text(code), text, code)

    def test_page_values_and_url(self):
        seen = []
        d = bp.weather_page("13.7563", "100.5018", fetch=lambda url: seen.append(url) or self.CUR)
        self.assertEqual((d["temp"], d["humidity"], d["wind"], d["text"], d["is_day"], d["unit"]),
                         (31, 70, 9, "RAIN", False, "C"))
        self.assertIn("latitude=13.7563", seen[0])
        self.assertIn("temperature_unit=celsius", seen[0])
        self.assertIn("wind_speed_unit=kmh", seen[0])

    def test_units(self):
        seen = []
        d = bp.weather_page("1", "2", fahrenheit=True, mph=True, fetch=lambda url: seen.append(url) or self.CUR)
        self.assertEqual((d["unit"], d["wind_unit"]), ("F", "MPH"))
        self.assertIn("fahrenheit", seen[0])
        self.assertIn("mph", seen[0])

    def test_bad_location_and_bad_reply(self):
        with self.assertRaises(bp.FetchError):
            bp.weather_page("", "2", fetch=lambda u: self.CUR)
        with self.assertRaises(bp.FetchError):
            bp.weather_page("1", "abc", fetch=lambda u: self.CUR)
        with self.assertRaises(bp.FetchError):
            bp.weather_page("1", "2", fetch=lambda u: {"error": True})


class GitHub(unittest.TestCase):
    def test_counts(self):
        d = bp.github_page("octocat", fetch=lambda url: {"followers": 99, "public_repos": 8})
        self.assertEqual(d, {"followers": 99, "repos": 8})

    def test_empty_and_odd_names_never_reach_the_network(self):
        def boom(url):
            raise AssertionError("no request expected")
        for name in ("", "  ", "a/b", "a b", "../x"):
            with self.assertRaises(bp.FetchError):
                bp.github_page(name, fetch=boom)

    def test_unknown_user(self):
        with self.assertRaises(bp.FetchError):
            bp.github_page("nobody", fetch=lambda url: {"message": "Not Found"})


class Stock(unittest.TestCase):
    def test_quote(self):
        seen = []
        d = bp.stock_page("aapl", "KEY", fetch=lambda url: seen.append(url) or
                          {"c": 110.0, "o": 100, "h": 112, "l": 99, "pc": 100})
        self.assertEqual((d["price"], d["open"], d["high"], d["low"]), (110.0, 100, 112, 99))
        self.assertAlmostEqual(d["change_pct"], 10.0)
        self.assertIn("symbol=AAPL", seen[0])
        self.assertIn("token=KEY", seen[0])

    def test_needs_ticker_and_key(self):
        for ticker, key in (("", "K"), ("AAPL", ""), ("AAPL", "  ")):
            with self.assertRaises(bp.FetchError):
                bp.stock_page(ticker, key, fetch=lambda u: {})

    def test_unknown_symbol_returns_zero_price(self):
        with self.assertRaises(bp.FetchError):
            bp.stock_page("ZZZZ", "K", fetch=lambda u: {"c": 0})


class Pages(unittest.TestCase):
    def test_order_matches_the_buddy_without_the_moon(self):
        self.assertEqual([k for k, _ in bp.PAGES],
                         ["face", "clock", "date", "weather", "stock", "github", "claude", "codex", "status", "wifi"])


class Feed(unittest.TestCase):
    """The bodies sent to a Buddy that has no Wi-Fi (the firmware's lib/feed checks them again)."""

    def test_weather_body_has_the_code_the_buddy_draws_from(self):
        cur = {"current": {"temperature_2m": 31.4, "relative_humidity_2m": 70, "weather_code": 61,
                           "wind_speed_10m": 9.2, "is_day": 0}}
        d = bp.weather_page("1", "2", fetch=lambda url: cur)
        self.assertEqual(bp.feed_body("weather", d),
                         {"temp": 31, "humidity": 70, "wind": 9, "code": 61, "is_day": False})

    def test_stock_body_adds_the_symbol(self):
        d = {"price": 327.74, "open": 323.1, "high": 329.6, "low": 322.2, "change_pct": 0.35}
        self.assertEqual(bp.feed_body("stock", d, " aapl "),
                         {"price": 327.74, "open": 323.1, "high": 329.6, "low": 322.2, "symbol": "AAPL"})
        self.assertNotIn("symbol", bp.feed_body("stock", d, ""))

    def test_github_body(self):
        self.assertEqual(bp.feed_body("github", {"followers": 12, "repos": 3}), {"followers": 12, "repos": 3})

    def test_unknown_page(self):
        with self.assertRaises(ValueError):
            bp.feed_body("moon", {})

    def test_time_body_is_utc_seconds(self):
        self.assertEqual(bp.time_body(1790000000.9), {"epoch": 1790000000})
        self.assertGreater(bp.time_body()["epoch"], 1700000000)


if __name__ == "__main__":
    unittest.main()
