import unittest
from unittest import mock

import status_push as sp
import usage_push as up


class StatusPush(unittest.TestCase):
    def run_main(self, argv):
        with mock.patch.object(up, "push_serial", return_value=(True, "")) as ps:
            code = sp.main(argv)
        return code, ps

    def test_serial_sends_status_command(self):
        code, ps = self.run_main(["--serial", "COM11", "busy"])
        self.assertEqual(code, 0)
        ps.assert_called_once_with("COM11", {"state": "busy"}, command="STATUS")

    def test_words_are_normalised(self):
        for word, want in [("Free", "free"), ("MEETING", "meeting"), ("in a meeting", "meeting")]:
            _, ps = self.run_main(["--serial", "COM11", word])
            self.assertEqual(ps.call_args[0][1], {"state": want})

    def test_refusal_is_exit_1(self):
        with mock.patch.object(up, "push_serial", return_value=(False, "no reply")):
            self.assertEqual(sp.main(["--serial", "COM11", "free"]), 1)

    def test_bad_state_is_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            sp.main(["--serial", "COM11", "away"])
        self.assertEqual(cm.exception.code, 2)

    def test_needs_a_target(self):
        with self.assertRaises(SystemExit) as cm:
            sp.main(["busy"])
        self.assertEqual(cm.exception.code, 2)

    def test_wifi_posts_to_status_path(self):
        with mock.patch.object(up, "load_token", return_value="t" * 20), \
             mock.patch.object(up, "push", return_value=(200, {"ok": True})) as p:
            self.assertEqual(sp.main(["10.0.0.5", "busy"]), 0)
        self.assertEqual(p.call_args[0][0], "http://10.0.0.5:8080")
        self.assertEqual(p.call_args[1]["path"], "/status")


if __name__ == "__main__":
    unittest.main()
