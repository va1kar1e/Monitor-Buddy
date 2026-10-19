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


class WifiProfiles(unittest.TestCase):
    def test_rules_match_the_buddy(self):
        self.assertIsNone(ba.wifi_problem("Home", "password1"))
        self.assertIsNone(ba.wifi_problem("Cafe", ""))                 # an open network
        self.assertIsNotNone(ba.wifi_problem("", "password1"))
        self.assertIsNotNone(ba.wifi_problem("x" * 33, "password1"))
        self.assertIsNotNone(ba.wifi_problem("Home", "short"))
        self.assertIsNotNone(ba.wifi_problem("Home", "p" * 64))

    def test_add_edit_delete_and_persist(self):
        c = controller()
        self.assertIsNone(c.save_profile("Office", "password1", True))
        self.assertIsNone(c.save_profile("Home", "password2", True))
        self.assertEqual([p["ssid"] for p in c.profiles()], ["Home", "Office"])          # sorted
        self.assertIn("already", c.save_profile("Home", "password3", True))              # add twice
        self.assertIsNone(c.save_profile("Home2", "password4", True, replacing="Home"))  # rename
        self.assertEqual([p["ssid"] for p in c.profiles()], ["Home2", "Office"])
        self.assertEqual(ba.Controller(c.path).profiles()[0]["password"], "password4")  # saved
        c.delete_profile("Office")
        self.assertEqual([p["ssid"] for p in ba.Controller(c.path).profiles()], ["Home2"])

    def test_password_not_stored_unless_asked(self):
        c = controller()
        c.save_profile("Guest", "password1", False)
        p = ba.Controller(c.path).profiles()[0]
        self.assertEqual((p["password"], p["remember"]), ("", False))
        self.assertNotIn("password1", c.path.read_text())

    def test_invalid_network_is_refused_and_not_saved(self):
        c = controller()
        self.assertIsNotNone(c.save_profile("Home", "short", True))
        self.assertEqual(c.profiles(), [])

    def test_profiles_are_not_shared_between_controllers(self):
        a, b = controller(), controller()
        a.save_profile("Home", "password1", True)
        self.assertEqual(b.profiles(), [])


class SetupOverUsb(unittest.TestCase):
    def test_wifi_goes_to_set_and_needs_usb(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "serial_command", return_value=({"ok": True, "cmd": "SET"}, "")) as sc:
            self.assertEqual(c.send_wifi("Home", "password1"), (True, ""))
        self.assertEqual(sc.call_args[0][:3], ("COM11", "SET", {"wifi": {"ssid": "Home", "password": "password1"}}))
        ok, msg = controller(mode="wifi", host="1.2.3.4").send_wifi("Home", "password1")
        self.assertFalse(ok)
        self.assertIn("USB", msg)

    def test_bad_wifi_never_reaches_the_buddy(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "serial_command") as sc:
            ok, msg = c.send_wifi("Home", "short")
        self.assertFalse(ok)
        sc.assert_not_called()

    def test_save_config_sends_only_the_changes_and_updates_the_app(self):
        c = controller(mode="usb", port="COM11")
        changes = {"lat": "1.5", "temp_unit": "fahrenheit", "wind_unit": "mph", "ticker": "MSFT",
                   "stock_key": "KEY", "pages": {"stock": False}}
        with mock.patch.object(up, "serial_command", return_value=({"ok": True, "cmd": "SET"}, "")) as sc:
            self.assertEqual(c.save_buddy_config(changes), (True, ""))
        self.assertEqual(sc.call_args[0][2], {"config": changes})
        s = ba.Controller(c.path).settings
        self.assertEqual((s["lat"], s["ticker"], s["finnhub_key"]), ("1.5", "MSFT", "KEY"))
        self.assertTrue(s["fahrenheit"] and s["mph"])

    def test_nothing_to_save(self):
        ok, msg = controller(mode="usb", port="COM11").save_buddy_config({})
        self.assertFalse(ok)
        self.assertIn("Nothing", msg)

    def test_the_buddys_complaints_are_shown_and_nothing_is_copied(self):
        c = controller(mode="usb", port="COM11", lat="13.7563")
        reply = {"ok": False, "cmd": "SET", "errors": {"lat": "must be -90 to 90", "ticker": "bad"}}
        with mock.patch.object(up, "serial_command", return_value=(reply, "")):
            ok, msg = c.save_buddy_config({"lat": "999", "ticker": "??"})
        self.assertFalse(ok)
        self.assertIn("lat: must be -90 to 90", msg)
        self.assertEqual(c.settings["lat"], "13.7563")

    def test_no_reply_is_reported(self):
        c = controller(mode="usb", port="COM11")
        with mock.patch.object(up, "serial_command", return_value=(None, "no reply")):
            self.assertEqual(c.send_wifi("Home", "password1"), (False, "no reply"))


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
            self.assertEqual(app.listbox.size(), len(ba.bp.PAGES) + 1)   # and Setup
            app.show_page("weather", {"temp": 31, "humidity": 70, "wind": 9, "text": "CLEAR", "is_day": True,
                                      "unit": "C", "wind_unit": "KMH"}, None)
            self.assertEqual(app.page_labels[("weather", "temp")].cget("text"), "31\u00b0C")
            app.show_page("stock", None, "set a Finnhub key")
            self.assertEqual(app.page_labels[("stock", "error")].cget("text"), "set a Finnhub key")
            app.show_page("wifi", {"ssid": "Home", "ip": "192.168.1.186", "rssi": -52, "connected": True}, None)
            self.assertEqual(app.page_labels[("wifi", "ip")].cget("text"), "192.168.1.186")
            app.fill_setup({"mount": "right", "theme": 2, "tz_name": "Asia/Bangkok", "tz_rule": "<+07>-7",
                            "lat": "13.7", "lon": "100.5", "temp_unit": "celsius", "wind_unit": "kmh",
                            "github_user": "octo", "ticker": "AVGO", "stock_key": "K",
                            "pages": {"face": True, "stock": False}})
            self.assertEqual(app.cfg_vars["theme"].get(), "2")
            self.assertFalse(app.cfg_vars["pages.stock"].get())
            self.assertEqual(app.cfg_dirty, set())          # filling is not editing
            app.cfg_vars["ticker"].set("MSFT")
            app.cfg_vars["theme"].set("3")
            self.assertEqual(app.cfg_dirty, {"ticker", "theme"})
            app.pick_tz(0)                                   # Bangkok preset
            self.assertEqual(app.cfg_vars["tz_rule"].get(), "<+07>-7")
            self.assertIn("tz_name", app.cfg_dirty)
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
