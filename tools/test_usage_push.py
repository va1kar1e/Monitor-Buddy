import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import usage_push as up

TODAY = dt.date.today()


def stamp(days_ago, hour=12):
    """A UTC timestamp that falls on the local date `days_ago` days back."""
    local = dt.datetime.combine(TODAY - dt.timedelta(days=days_ago), dt.time(hour)).astimezone()
    return local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def tw(totals):
    """Just the token counts of a totals dict."""
    return {"today": totals["today"], "week": totals["week"]}


def claude_msg(msg_id, req_id, days_ago, inp, out, cache_read=0, model=None, write_1h=0):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cache_read}
    if write_1h:
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": write_1h, "ephemeral_5m_input_tokens": 0}
    msg = {"id": msg_id, "usage": usage}
    if model:
        msg["model"] = model
    return {"timestamp": stamp(days_ago), "requestId": req_id, "message": msg}


def codex_event(days_ago, inp, cached, out, limits=None):
    rec = {"timestamp": stamp(days_ago), "type": "event_msg",
           "payload": {"type": "token_count",
                       "info": {"total_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                                      "output_tokens": out}}}}
    if limits is not None:
        rec["payload"]["rate_limits"] = limits
    return rec


class ClaudeUsage(unittest.TestCase):
    def test_counts_input_and_output_not_cache_reads(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "p" / "s.jsonl", [claude_msg("m1", "r1", 0, 10, 5, cache_read=99999)])
            self.assertEqual(tw(up.claude_usage(Path(d), TODAY)), {"today": 15, "week": 15})

    def test_same_message_logged_twice_counts_once(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "a.jsonl", [claude_msg("m1", "r1", 0, 10, 5)])
            write_jsonl(Path(d) / "b.jsonl", [claude_msg("m1", "r1", 0, 10, 5)])
            self.assertEqual(up.claude_usage(Path(d), TODAY)["today"], 15)

    def test_window_is_seven_days(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "s.jsonl", [claude_msg("a", "1", 0, 1, 0), claude_msg("b", "2", 6, 10, 0),
                                              claude_msg("c", "3", 7, 100, 0)])
            self.assertEqual(tw(up.claude_usage(Path(d), TODAY)), {"today": 1, "week": 11})

    def test_missing_directory_and_junk_lines(self):
        self.assertEqual(tw(up.claude_usage(Path("/nonexistent-dir-xyz"), TODAY)), {"today": 0, "week": 0})
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.jsonl").write_text("not json\n{\"message\": 5}\n{broken\n", encoding="utf-8")
            self.assertEqual(tw(up.claude_usage(Path(d), TODAY)), {"today": 0, "week": 0})


class CodexUsage(unittest.TestCase):
    def test_running_total_counts_growth_once(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "rollout-1.jsonl", [
                codex_event(0, 100, 40, 10),   # 60 + 10 = 70
                codex_event(0, 100, 40, 10),   # repeated event: nothing new
                codex_event(0, 150, 60, 20),   # now 90 + 20 = 110, growth 40
            ])
            self.assertEqual(tw(up.codex_usage(Path(d), TODAY)), {"today": 110, "week": 110})

    def test_limits_from_newest_event(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "rollout-1.jsonl", [
                codex_event(1, 10, 0, 0, {"primary": {"used_percent": 10, "resets_in_seconds": 600},
                                          "secondary": None}),
                codex_event(0, 20, 0, 0, {"primary": {"used_percent": 42.4, "resets_in_seconds": 7980},
                                          "secondary": {"used_percent": 17}}),
            ])
            got = up.codex_usage(Path(d), TODAY)
            self.assertEqual((got["pct1"], got["pct2"], got["reset1"]), (42, 17, 133))

    def test_null_limits_leave_no_percent(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "rollout-1.jsonl", [
                codex_event(0, 10, 0, 0, {"primary": None, "secondary": None})])
            got = up.codex_usage(Path(d), TODAY)
            self.assertNotIn("pct1", got)
            self.assertNotIn("reset1", got)


class Cost(unittest.TestCase):
    def test_claude_dollars_per_token_kind(self):
        with tempfile.TemporaryDirectory() as d:
            # sonnet 5.5: $2 in, $10 out, cache read $0.20, 1 hour cache write 2x input = $4
            write_jsonl(Path(d) / "s.jsonl", [claude_msg("m", "r", 0, 1_000_000, 1_000_000,
                                                          cache_read=1_000_000, model="claude-sonnet-5-5",
                                                          write_1h=1_000_000)])
            got = up.claude_usage(Path(d), TODAY)
            self.assertAlmostEqual(got["today_usd"], 2 + 10 + 0.2 + 4)
            self.assertAlmostEqual(got["week_usd"], got["today_usd"])
            self.assertEqual(got["_unpriced"], {})

    def test_unknown_model_counts_tokens_but_no_dollars(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "s.jsonl", [claude_msg("m", "r", 0, 10, 5, model="claude-future-9")])
            got = up.claude_usage(Path(d), TODAY)
            self.assertEqual(got["today"], 15)
            self.assertEqual(got["today_usd"], 0.0)
            self.assertEqual(got["_unpriced"], {"claude-future-9": 15})

    def test_synthetic_model_is_not_reported(self):
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "s.jsonl", [claude_msg("m", "r", 0, 10, 5, model="<synthetic>")])
            self.assertEqual(up.claude_usage(Path(d), TODAY)["_unpriced"], {})

    def test_codex_dollars_use_the_turn_model(self):
        with tempfile.TemporaryDirectory() as d:
            # gpt-6-luna: $0.10 in, $0.01 cached, $0.50 out per 1M
            write_jsonl(Path(d) / "rollout-1.jsonl", [
                {"timestamp": stamp(0), "type": "turn_context", "payload": {"model": "gpt-6-luna"}},
                codex_event(0, 2_000_000, 1_000_000, 1_000_000),
            ])
            got = up.codex_usage(Path(d), TODAY)
            self.assertAlmostEqual(got["today_usd"], 1 * 0.10 + 1 * 0.01 + 1 * 0.50)
            self.assertEqual(got["today"], 2_000_000)   # fresh input + output, no cached

    def test_custom_prices_override(self):
        prices = dict(up.PRICES, **{"my-model": {"in": 1.0, "out": 2.0}})
        self.assertAlmostEqual(up.cost_usd(prices, "my-model", 1_000_000, 0, 1_000_000), 3.0)
        self.assertIsNone(up.cost_usd(prices, "other", 5))


class Month(unittest.TestCase):
    def test_month_counts_this_calendar_month_only(self):
        today = dt.date(2026, 10, 19)
        def at(day, tokens):
            local = dt.datetime.combine(day, dt.time(12)).astimezone()
            return {"timestamp": local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "requestId": str(day), "message": {"id": str(day), "usage": {"input_tokens": tokens, "output_tokens": 0}}}
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "s.jsonl", [
                at(dt.date(2026, 10, 19), 1),      # today
                at(dt.date(2026, 10, 14), 10),     # inside the 7 days and the month
                at(dt.date(2026, 10, 1), 100),     # the month only
                at(dt.date(2026, 9, 30), 1000),    # last month: inside the 7 days? no, 19 days back
                at(dt.date(2026, 10, 20), 5),      # in the future: ignored
            ])
            got = up.claude_usage(Path(d), today)
        self.assertEqual((got["today"], got["week"], got["month"]), (1, 11, 111))

    def test_week_reaching_into_last_month_is_not_in_the_month(self):
        today = dt.date(2026, 10, 3)
        local = dt.datetime.combine(dt.date(2026, 9, 30), dt.time(12)).astimezone()
        rec = {"timestamp": local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
               "requestId": "r", "message": {"id": "m", "usage": {"input_tokens": 7, "output_tokens": 0}}}
        with tempfile.TemporaryDirectory() as d:
            write_jsonl(Path(d) / "s.jsonl", [rec])
            got = up.claude_usage(Path(d), today)
        self.assertEqual((got["week"], got["month"]), (7, 0))

    def test_month_limit_is_sent_per_assistant(self):
        with tempfile.TemporaryDirectory() as d:
            body = up.build_body(None, TODAY, Path(d), Path(d), month_limit=400)
            self.assertEqual(body["claude"]["month_limit_usd"], 400)
            self.assertEqual(body["codex"]["month_limit_usd"], 400)
            self.assertEqual(body["codex"]["month_usd"], 0.0)
            self.assertNotIn("month_limit_usd", up.build_body(None, TODAY, Path(d), Path(d))["claude"])


class Body(unittest.TestCase):
    def test_only_selects_one_assistant(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(list(up.build_body("codex", TODAY, Path(d), Path(d))), ["codex"])
            body = up.build_body(None, TODAY, Path(d), Path(d))
            self.assertNotIn("_unpriced", body["claude"])
            self.assertEqual(body["claude"]["today_usd"], 0.0)
            self.assertEqual(list(up.build_body(None, TODAY, Path(d), Path(d))), ["claude", "codex"])


class Token(unittest.TestCase):
    def test_created_once_then_reused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tok"
            first = up.load_token(path)
            self.assertGreaterEqual(len(first), 16)   # the firmware requires 16-64
            self.assertLessEqual(len(first), 64)
            self.assertEqual(up.load_token(path), first)


if __name__ == "__main__":
    unittest.main()
