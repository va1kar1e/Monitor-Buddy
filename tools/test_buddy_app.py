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
            app = ba.App(root, controller())
            self.assertEqual(set(app.buttons), {"free", "busy", "meeting"})
            app.show_usage({"claude": {"today": 76217, "week": 123158, "today_usd": 3.88, "week_usd": 6.24},
                            "codex": {"today": 0, "week": 11094439, "today_usd": 0.0, "week_usd": 203.23,
                                      "pct1": 42, "reset1": 134}})
            self.assertEqual(app.cells[("claude", "today")].cget("text"), "76.2k   $3.88")
            self.assertEqual(app.cells[("codex", "week")].cget("text"), "11.0M   $203.23")
            self.assertEqual(app.cells[("codex", "limit")].cget("text"), "Limit 42%  resets in 2 h 14 m")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
