import random
import time
import unittest

import jiggler as jg


class FakeBackend:
    def __init__(self, pos=(500, 400)):
        self.pos = pos
        self.moves = []

    def position(self):
        return self.pos

    def move_to(self, x, y):
        self.pos = (x, y)
        self.moves.append((x, y))


def make(mode="steady", **kw):
    b = FakeBackend()
    events = []
    j = jg.Jiggler(b, mode=mode, pause=0, rng=random.Random(1), on_event=events.append, **kw)
    return j, b, events


class StepTest(unittest.TestCase):
    def test_steady_alternates_and_always_returns(self):
        j, b, _ = make("steady", distance=6)
        self.assertEqual(j.step(), (-6, 0))
        self.assertEqual(j.step(), (6, 0))
        self.assertEqual(b.pos, (500, 400))
        self.assertEqual(b.moves, [(494, 400), (500, 400), (506, 400), (500, 400)])

    def test_random_stays_within_distance_and_returns(self):
        j, b, _ = make("random", distance=10)
        seen = set()
        for _ in range(200):
            dx, dy = j.step()
            self.assertTrue((dx, dy) != (0, 0))
            self.assertLessEqual(max(abs(dx), abs(dy)), 10)
            self.assertEqual(b.pos, (500, 400))
            seen.add((dx, dy))
        self.assertGreater(len(seen), 20)          # really varies

    def test_user_moving_the_mouse_skips_the_nudge(self):
        j, b, _ = make("steady")
        j.step()
        b.pos = (700, 300)                          # the user moved it
        self.assertIsNone(j.step())
        self.assertEqual(j.skipped, 1)
        self.assertIsNotNone(j.step())              # and it carries on from there
        self.assertEqual(b.pos, (700, 300))

    def test_a_one_pixel_difference_is_not_the_user(self):
        j, b, _ = make("steady")
        j.step()
        b.pos = (501, 400)
        self.assertIsNotNone(j.step())


class DelayAndLimitsTest(unittest.TestCase):
    def test_steady_delay_is_fixed(self):
        j, _, _ = make("steady", interval=20)
        self.assertEqual({j.next_delay() for _ in range(10)}, {20.0})

    def test_random_delay_is_between_half_and_one_and_a_half(self):
        j, _, _ = make("random", interval=20)
        delays = [j.next_delay() for _ in range(200)]
        self.assertTrue(all(10 <= d <= 30 for d in delays))
        self.assertGreater(len(set(delays)), 100)

    def test_values_are_clamped_and_bad_mode_falls_back(self):
        j = jg.Jiggler(FakeBackend(), mode="nope", interval=0, distance=999)
        self.assertEqual((j.mode, j.interval, j.distance), ("steady", 1.0, 50))


class ThreadTest(unittest.TestCase):
    def test_start_runs_and_stop_ends_it(self):
        j, b, events = make("steady", interval=1)
        j.interval = 0.01                           # faster than the allowed minimum, for the test
        j.start()
        deadline = time.time() + 3
        while j.nudges < 3 and time.time() < deadline:
            time.sleep(0.01)
        j.stop()
        j.thread.join(2)
        self.assertGreaterEqual(j.nudges, 3)
        self.assertFalse(j.running)
        self.assertTrue(events[0].startswith("Mouse jiggler on"))
        self.assertEqual(events[-1], "Mouse jiggler off")

    def test_backend_failure_stops_and_reports(self):
        class Broken(FakeBackend):
            def move_to(self, x, y):
                raise jg.JigglerError("no permission")

        events = []
        j = jg.Jiggler(Broken(), pause=0, on_event=events.append)
        j.start()
        j.thread.join(2)
        self.assertFalse(j.running)
        self.assertIn("Mouse jiggler stopped: no permission", events)


if __name__ == "__main__":
    unittest.main()
