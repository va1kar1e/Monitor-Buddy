import tempfile
import unittest
from pathlib import Path
from unittest import mock

import buddy_app as ba
import usage_push as up


def controller(**settings):
    d = tempfile.mkdtemp()
    c = ba.Controller(Path(d) / "settings.json")
    c.settings.update(settings)
    return c


class Formatting(unittest.TestCase):
    def test_short_tokens(self):
        self.assertEqual(ba.short_tokens(0), "0")
        self.assertEqual(ba.short_tokens(812), "812")
        self.assertEqual(ba.short_tokens(4812), "4.8k")
        self.assertEqual(ba.short_tokens(76217), "76.2k")
        self.assertEqual(ba.short_tokens(150000), "150k")
        self.assertEqual(ba.short_tokens(11094439), "11.0M")

    def test_summary(self):
        body = {"claude": {"today": 76217, "today_usd": 3.8798}, "codex": {"today": 0, "today_usd": 0.0}}
        self.assertEqual(ba.summary(body), "Claude 76.2k / $3.88   Codex 0 / $0.00")
        self.assertEqual(ba.summary({}), "")


class Month(unittest.TestCase):
    def test_month_text_and_fraction(self):
        t = {"month_usd": 348.947, "month_limit_usd": 400}
        self.assertEqual(ba.month_text(t), "$348.95 of $400  (87%)")
        self.assertAlmostEqual(ba.month_fraction(t), 0.8724, places=3)
        self.assertEqual(ba.month_text({"month_usd": 12.5}), "$12.50")
        self.assertEqual(ba.month_fraction({"month_usd": 12.5}), 0.0)
        self.assertEqual(ba.month_fraction({"month_usd": 900, "month_limit_usd": 400}), 1.0)

    def test_limit_setting_goes_into_the_body(self):
        c = controller(month_limit=250)
        with mock.patch.object(up, "build_body", return_value={}) as b:
            c.read_usage()
        self.assertEqual(b.call_args[1]["month_limit"], 250)
        c = controller(month_limit=0)
        with mock.patch.object(up, "build_body", return_value={}) as b:
            c.read_usage()
        self.assertIsNone(b.call_args[1]["month_limit"])


class Pages(unittest.TestCase):
    def test_fetch_page_uses_the_saved_settings(self):
        c = controller(lat="1.5", lon="2.5", fahrenheit=True, mph=True, github_user="octo", ticker="msft",
                       finnhub_key="K")
        with mock.patch.object(ba.bp, "weather_page", return_value={}) as w, \
             mock.patch.object(ba.bp, "github_page", return_value={}) as g, \
             mock.patch.object(ba.bp, "stock_page", return_value={}) as s:
            c.fetch_page("weather")
            c.fetch_page("github")
            c.fetch_page("stock")
        w.assert_called_once_with("1.5", "2.5", True, True)
        g.assert_called_once_with("octo")
        s.assert_called_once_with("msft", "K")
        with self.assertRaises(ValueError):
            c.fetch_page("moon")

    def test_wifi_page_over_wifi_knows_only_the_address(self):
        c = controller(mode="wifi", host="10.0.0.5:8080")
        self.assertEqual(c.wifi_page(), {"ssid": None, "ip": "10.0.0.5", "rssi": None, "connected": True})
        with self.assertRaises(ba.bp.FetchError):
            controller(mode="wifi", host="").wifi_page()

    def test_wifi_page_over_usb_reads_info(self):
        c = controller(mode="usb", port="COM11")
        reply = {"ok": True, "cmd": "INFO",
                 "wifi": {"ssid": "Home", "ip": "192.168.1.186", "rssi": -52, "connected": True}}
        with mock.patch.object(up, "serial_command", return_value=(reply, "")) as sc:
            page = c.wifi_page()
        sc.assert_called_once_with("COM11", "INFO")
        self.assertEqual(page, {"ssid": "Home", "ip": "192.168.1.186", "rssi": -52, "connected": True})

    def test_wifi_page_old_firmware_has_no_ip(self):
        c = controller(mode="usb", port="COM11")
        reply = {"ok": True, "cmd": "INFO", "wifi": {"ssid": "Home", "connected": True, "rssi": -50}}
        with mock.patch.object(up, "serial_command", return_value=(reply, "")):
            self.assertIsNone(c.wifi_page()["ip"])

    def test_wifi_page_no_answer_is_a_readable_error(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "serial_command", return_value=(None, "no reply")):
            with self.assertRaises(ba.bp.FetchError) as cm:
                c.wifi_page()
        self.assertIn("no reply", str(cm.exception))

    def test_load_from_buddy_copies_settings_and_saves(self):
        c = controller(mode="usb", port="COM11")
        reply = {"ok": True, "cmd": "GET",
                 "config": {"lat": "1.3", "lon": "103.8", "github_user": "octo", "ticker": "AVGO",
                            "temp_unit": "fahrenheit", "wind_unit": "mph"}}
        with mock.patch.object(up, "serial_command", return_value=(reply, "")):
            c.load_from_buddy()
        self.assertEqual((c.settings["lat"], c.settings["github_user"], c.settings["ticker"]),
                         ("1.3", "octo", "AVGO"))
        self.assertTrue(c.settings["fahrenheit"] and c.settings["mph"])
        self.assertEqual(ba.Controller(c.path).settings["ticker"], "AVGO")   # saved
        with self.assertRaises(ba.bp.FetchError):
            controller(mode="wifi", host="1.2.3.4").load_from_buddy()


class Colors(unittest.TestCase):
    def test_bar_color_thresholds(self):
        self.assertEqual(ba.bar_color(0.0), ba.BLUE)
        self.assertEqual(ba.bar_color(0.69), ba.BLUE)
        self.assertEqual(ba.bar_color(0.7), ba.YELLOW)
        self.assertEqual(ba.bar_color(0.89), ba.YELLOW)
        self.assertEqual(ba.bar_color(0.9), ba.RED)
        self.assertEqual(ba.bar_color(1.0), ba.RED)


class Limits(unittest.TestCase):
    def test_limit_text(self):
        self.assertEqual(ba.limit_text({"pct1": 42, "pct2": 17, "reset1": 134}), "Limit 42%  Week 17%  resets in 2 h 14 m")
        self.assertEqual(ba.limit_text({"pct2": 5}), "Week 5%")
        self.assertEqual(ba.limit_text({"reset1": 5}), "resets in 5 m")
        self.assertEqual(ba.limit_text({"today": 1}), "")


class Sending(unittest.TestCase):
    def test_read_usage_needs_no_buddy(self):
        c = controller(mode="usb", port="")
        with mock.patch.object(up, "build_body", return_value={"claude": {"today": 1}}):
            self.assertEqual(c.read_usage(), {"claude": {"today": 1}})
            ok, msg, body = c.send_usage()
        self.assertFalse(ok)
        self.assertIn("USB port", msg)
        self.assertEqual(body, {"claude": {"today": 1}})   # still shown in the window

    def test_needs_a_target(self):
        self.assertIn("USB port", controller(mode="usb", port="").send_status("busy")[1])
        self.assertIn("Wi-Fi address", controller(mode="wifi", host=" ").send_status("busy")[1])

    def test_usb_status(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "push_serial", return_value=(True, "")) as ps:
            self.assertEqual(c.send_status("meeting"), (True, ""))
        ps.assert_called_once_with("COM11", {"state": "meeting"}, command="STATUS")

    def test_usb_refusal_is_reported(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "push_serial", return_value=(False, "no reply")):
            self.assertEqual(c.send_status("busy"), (False, "no reply"))

    def test_wifi_adds_default_port_and_path(self):
        c = controller(mode="wifi", host="10.0.0.5")
        with mock.patch.object(up, "load_token", return_value="t" * 20), \
             mock.patch.object(up, "push", return_value=(200, {"ok": True})) as p:
            self.assertEqual(c.send_status("free"), (True, ""))
        self.assertEqual(p.call_args[0][0], "http://10.0.0.5:8080")
        self.assertEqual(p.call_args[1]["path"], "/status")

    def test_wifi_refusal_message(self):
        c = controller(mode="wifi", host="10.0.0.5")
        with mock.patch.object(up, "load_token", return_value="t" * 20), \
             mock.patch.object(up, "push", return_value=(403, {"error": "wrong token"})):
            ok, msg = c.send_status("free")
        self.assertFalse(ok)
        self.assertIn("403", msg)
        self.assertIn("wrong token", msg)

    def test_usage_sends_built_body(self):
        c = controller(mode="usb", port="COM11")
        body = {"claude": {"today": 1}}
        with mock.patch.object(up, "build_body", return_value=body), \
             mock.patch.object(up, "push_serial", return_value=(True, "")) as ps:
            ok, msg, sent = c.send_usage()
        self.assertTrue(ok)
        self.assertEqual(sent, body)
        self.assertEqual(ps.call_args[1]["command"], "USAGE")


class Settings(unittest.TestCase):
    def test_saved_and_reloaded(self):
        d = tempfile.mkdtemp()
        path = Path(d) / "s.json"
        c = ba.Controller(path)
        c.settings.update(mode="wifi", host="1.2.3.4", interval=30)
        c.save()
        again = ba.Controller(path)
        self.assertEqual((again.settings["mode"], again.settings["host"], again.settings["interval"]),
                         ("wifi", "1.2.3.4", 30))

    def test_corrupt_file_falls_back_to_defaults(self):
        d = tempfile.mkdtemp()
        path = Path(d) / "s.json"
        path.write_text("{not json")
        self.assertEqual(ba.Controller(path).settings, ba.DEFAULTS)


class Window(unittest.TestCase):
    def test_window_builds(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            app = ba.App(root, controller(), autostart=False)
            self.assertEqual(set(app.buttons), {"free", "busy", "meeting"})
            self.assertEqual(app.listbox.size(), len(ba.bp.PAGES))
            app.show_page("weather", {"temp": 31, "humidity": 70, "wind": 9, "text": "CLEAR", "is_day": True,
                                      "unit": "C", "wind_unit": "KMH"}, None)
            self.assertEqual(app.page_labels[("weather", "temp")].cget("text"), "31\u00b0C")
            app.show_page("stock", None, "set a Finnhub key")
            self.assertEqual(app.page_labels[("stock", "error")].cget("text"), "set a Finnhub key")
            app.show_page("wifi", {"ssid": "Home", "ip": "192.168.1.186", "rssi": -52, "connected": True}, None)
            self.assertEqual(app.page_labels[("wifi", "ip")].cget("text"), "192.168.1.186")
            app.show_page("github", {"followers": 1234, "repos": 5}, None)
            self.assertEqual(app.page_labels[("github", "followers")].cget("text"), "1,234 followers")
            app.show_usage({"claude": {"today": 76217, "week": 123158, "today_usd": 3.88, "week_usd": 6.24},
                            "codex": {"today": 0, "week": 11094439, "today_usd": 0.0, "week_usd": 203.23,
                                      "month": 15611974, "month_usd": 348.95, "month_limit_usd": 400,
                                      "pct1": 42, "reset1": 134}})
            self.assertEqual(app.cells[("codex", "month")].cget("text"), "15.6M   $348.95")
            self.assertAlmostEqual(app.cells[("codex", "bar")].fraction, 0.8724, places=3)
            self.assertEqual(app.cells[("claude", "today")].cget("text"), "76.2k   $3.88")
            self.assertEqual(app.cells[("codex", "week")].cget("text"), "11.0M   $203.23")
            self.assertEqual(app.cells[("codex", "limit")].cget("text"),
                             "Month $348.95 of $400  (87%)  Limit 42%  resets in 2 h 14 m")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
