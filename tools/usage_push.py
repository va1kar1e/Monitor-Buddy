#!/usr/bin/env python3
"""Push Claude Code and Codex token usage from this PC to a Monitor Buddy.

    python tools/usage_push.py 192.168.1.50              push every 60 s over Wi-Fi
    python tools/usage_push.py --serial COM11            push over the USB cable
    python tools/usage_push.py 192.168.1.50 --once       push once and exit
    python tools/usage_push.py 192.168.1.50 --dry-run    print the body, send nothing
    python tools/usage_push.py 192.168.1.50 --only codex

The Buddy prints its address in the serial log when it joins Wi-Fi
("usage: listening on http://<ip>:8080/usage"). The tool reads the local logs:

  Claude Code  ~/.claude/projects/**/*.jsonl   (assistant messages with usage)
  Codex        ~/.codex/sessions/**/rollout-*.jsonl   (token_count events)

Numbers are tokens, input + output only (cache reads are left out), for today
and for the last 7 days, in this PC's local time, plus an estimate in US dollars
at API list prices (PRICES below; --prices FILE adds or changes models). The
dollars include cached input and cache writes, which the token count leaves out,
and are what the same usage would cost through the API: a Claude Max or
ChatGPT Business plan is billed differently. A model without a price counts as
tokens only, and the tool says so on stderr. Codex logs that carry
rate-limit percentages (some plans do not) also fill the Buddy's limit bars;
Claude Code keeps no limit numbers locally, so its page shows tokens only.

Over USB (--serial) the Buddy needs no address and no token, and Wi-Fi does not
have to be set up; it needs pyserial (pip install pyserial). The port is opened
for each push and closed again, so the web flasher can use it in between.

Over Wi-Fi the first push pairs the Buddy with a random token kept in
~/.monitor-buddy-usage-token (override with --token-file). Later pushes must use
the same token. Plain HTTP on your own network: anyone on it can read the
traffic, so pair on a network you trust.

Exit codes: 0 ok, 1 the Buddy refused or could not be reached, 2 bad arguments.
Standard library only, plus pyserial for --serial.
"""
import argparse
import datetime as dt
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DAYS = 7
DEFAULT_PORT = 8080

# US dollars per 1,000,000 tokens, from Anthropic's and OpenAI's price lists
# (October 2026). These are API list prices: a subscription plan (Claude Max,
# ChatGPT Business) is billed differently, so the dollars are what the same
# usage would cost through the API. Standard short-context rates only; OpenAI
# bills requests over 272K input tokens at higher rates, which is not modelled.
# Claude cache writes default to 1.25x input (5 minute) and 2x (1 hour), cache
# reads to 0.1x, unless a model lists its own. A model missing here counts as
# tokens only, and the tool says so; add it with --prices FILE.
PRICES = {
    "claude-fable-5-1":  {"in": 10.0, "out": 50.0, "cache_read": 0.25},
    "claude-fable-5":    {"in": 10.0, "out": 50.0, "cache_read": 0.25},
    "claude-opus-5-5":   {"in": 4.0,  "out": 20.0, "cache_read": 0.20},
    "claude-opus-5":     {"in": 5.0,  "out": 25.0},
    "claude-opus-4-8":   {"in": 5.0,  "out": 25.0},
    "claude-opus-4-7":   {"in": 5.0,  "out": 25.0},
    "claude-opus-4-6":   {"in": 5.0,  "out": 25.0},
    "claude-sonnet-5-5": {"in": 2.0,  "out": 10.0, "cache_read": 0.20},
    "claude-sonnet-5":   {"in": 2.0,  "out": 10.0},
    "claude-sonnet-4-6": {"in": 3.0,  "out": 15.0},
    "claude-haiku-5-5":  {"in": 0.10, "out": 0.50},
    "claude-haiku-4-5":  {"in": 1.0,  "out": 5.0},
    "gpt-6-luna":        {"in": 0.10, "out": 0.50,  "cache_read": 0.01},
    "gpt-6-astra":       {"in": 10.0, "out": 50.0,  "cache_read": 1.0},
    "gpt-6-sol":         {"in": 2.0,  "out": 10.0,  "cache_read": 0.20},
    "gpt-6.1-sol":       {"in": 2.0,  "out": 10.0,  "cache_read": 0.10},
    "gpt-5.3-codex":     {"in": 1.75, "out": 14.0,  "cache_read": 0.175},
}


def cost_usd(prices, model, fresh_in=0, cache_read=0, out=0, write_5m=0, write_1h=0):
    """Dollars for one call's tokens, or None when the model has no price."""
    p = prices.get(model)
    if not p:
        return None
    per = 1e-6
    return per * (fresh_in * p["in"]
                  + cache_read * p.get("cache_read", 0.1 * p["in"])
                  + out * p["out"]
                  + write_5m * p.get("cache_write_5m", 1.25 * p["in"])
                  + write_1h * p.get("cache_write_1h", 2.0 * p["in"]))


def local_date(ts):
    """Local calendar date of an ISO-8601 timestamp, or None if unreadable."""
    if not isinstance(ts, str):
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return None


def new_totals():
    # "_unpriced" (model -> tokens) is for the warning only and never sent.
    return {"today": 0, "week": 0, "today_usd": 0.0, "week_usd": 0.0, "_unpriced": {}}


def add(totals, day, tokens, today, usd=0.0, unpriced_model=None):
    if day is None or tokens <= 0:
        return
    age = (today - day).days
    if 0 <= age < DAYS:
        totals["week"] += tokens
        totals["week_usd"] += usd
        if age == 0:
            totals["today"] += tokens
            totals["today_usd"] += usd
        if unpriced_model is not None:
            totals["_unpriced"][unpriced_model] = totals["_unpriced"].get(unpriced_model, 0) + tokens


def recent_files(root, pattern, today):
    """Files under root touched in the window (older files cannot add to it)."""
    cutoff = time.time() - (DAYS + 1) * 86400
    out = []
    if not root.is_dir():
        return out
    for f in root.rglob(pattern):
        try:
            if f.stat().st_mtime >= cutoff:
                out.append(f)
        except OSError:
            pass
    return out


def lines_of(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        yield json.loads(line)
                    except ValueError:
                        pass
    except OSError:
        return


def claude_usage(root, today, prices=PRICES):
    """Tokens from Claude Code's transcripts. The same assistant message can be
    logged more than once (streaming, resumed sessions), so count each
    message id + request id once."""
    totals = new_totals()
    seen = set()
    for f in recent_files(root, "*.jsonl", today):
        for rec in lines_of(f):
            msg = rec.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            key = (msg.get("id"), rec.get("requestId"))
            if key != (None, None):
                if key in seen:
                    continue
                seen.add(key)
            u = msg["usage"]
            fresh, out = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
            cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
            w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
            if not cc:   # older logs: one total, 5 minute cache
                w5 = int(u.get("cache_creation_input_tokens") or 0)
            model = msg.get("model")
            usd = cost_usd(prices, model, fresh, int(u.get("cache_read_input_tokens") or 0), out, w5, w1)
            if usd is None and model != "<synthetic>":
                add(totals, local_date(rec.get("timestamp")), fresh + out, today, 0.0, model or "unknown")
            else:
                add(totals, local_date(rec.get("timestamp")), fresh + out, today, usd or 0.0)
    return totals


def codex_usage(root, today, prices=PRICES):
    """Tokens and limits from Codex rollout logs. token_count events carry the
    session's running total, so each event adds the growth since the previous
    one; repeated events add nothing. Limits come from the newest event that
    has them."""
    totals = new_totals()
    limits = None   # (timestamp string, primary, secondary)
    for f in recent_files(root, "rollout-*.jsonl", today):
        prev = (0, 0, 0)   # fresh input, cached input, output so far in this session
        model = None
        for rec in lines_of(f):
            p = rec.get("payload")
            if rec.get("type") == "turn_context" and isinstance(p, dict) and p.get("model"):
                model = p["model"]
                continue
            if rec.get("type") != "event_msg" or not isinstance(p, dict) or p.get("type") != "token_count":
                continue
            info = p.get("info")
            if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                t = info["total_token_usage"]
                cached = int(t.get("cached_input_tokens") or 0)
                running = (max(int(t.get("input_tokens") or 0) - cached, 0), cached,
                           int(t.get("output_tokens") or 0))
                if sum(running) > sum(prev):
                    d = tuple(max(a - b, 0) for a, b in zip(running, prev))
                    usd = cost_usd(prices, model, d[0], d[1], d[2])
                    # Cached input is not a "token" in the count shown (see the
                    # header), but it is billed, so it is in the dollars.
                    tokens = d[0] + d[2]
                    add(totals, local_date(rec.get("timestamp")), tokens, today,
                        usd or 0.0, None if usd is not None else (model or "unknown"))
                    prev = running
            rl = p.get("rate_limits")
            if isinstance(rl, dict) and (rl.get("primary") or rl.get("secondary")):
                ts = rec.get("timestamp") or ""
                if limits is None or ts > limits[0]:
                    limits = (ts, rl.get("primary"), rl.get("secondary"))
    if limits:
        _, primary, secondary = limits
        if isinstance(primary, dict) and isinstance(primary.get("used_percent"), (int, float)):
            totals["pct1"] = max(0, min(100, round(primary["used_percent"])))
            secs = primary.get("resets_in_seconds")
            if isinstance(secs, (int, float)) and secs >= 0:
                totals["reset1"] = int(secs // 60)
        if isinstance(secondary, dict) and isinstance(secondary.get("used_percent"), (int, float)):
            totals["pct2"] = max(0, min(100, round(secondary["used_percent"])))
    return totals


def build_body(only, today, claude_root, codex_root, prices=PRICES):
    """The body to send; unpriced models are reported on stderr, never sent."""
    body = {}
    if only in (None, "claude"):
        body["claude"] = claude_usage(claude_root, today, prices)
    if only in (None, "codex"):
        body["codex"] = codex_usage(codex_root, today, prices)
    for name, t in body.items():
        for model, tokens in sorted(t.pop("_unpriced", {}).items()):
            print(f"note: no price for {model} ({name}, {tokens} tokens): not in the dollars. "
                  f"Add it with --prices", file=sys.stderr)
        t["today_usd"] = round(t["today_usd"], 4)
        t["week_usd"] = round(t["week_usd"], 4)
    return body


def load_token(path):
    p = Path(path).expanduser()
    if p.exists():
        tok = p.read_text().strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(24)
    p.write_text(tok + "\n")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return tok


def push(base, token, body, timeout=8, path="/usage"):
    """POST body. Returns (status, parsed reply or None)."""
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Usage-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def push_serial(port, body, timeout=3.0, command="USAGE"):
    """Send "@MB <command> <body>" and wait for the reply. Returns (ok, error text)."""
    try:
        import serial
    except ImportError:
        raise SystemExit("--serial needs pyserial:  pip install pyserial")
    # DTR/RTS low before opening: on the S3's USB port a raised line resets the board.
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, 115200, 0.2
    ser.dtr = False
    ser.rts = False
    try:
        ser.open()
        ser.write(b"@MB " + command.encode() + b" " + json.dumps(body, separators=(",", ":")).encode() + b"\n")
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            buf += ser.read(256)
            for line in buf.split(b"\n"):
                line = line.strip()
                if line.startswith(b"@MB ") and b'"cmd":"' + command.encode() + b'"' in line:
                    reply = json.loads(line[4:])
                    return bool(reply.get("ok")), reply.get("error", "")
        return False, "no reply (is this firmware new enough to have " + command + "?)"
    except (serial.SerialException, OSError) as e:
        return False, str(e)
    finally:
        ser.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Push Claude Code / Codex token usage to a Monitor Buddy.")
    ap.add_argument("host", nargs="?", help="the Buddy's IP address or host name, optionally :port")
    ap.add_argument("--serial", metavar="PORT", help="push over USB serial instead (COM11, /dev/ttyACM0)")
    ap.add_argument("--interval", type=int, default=60, help="seconds between pushes (default 60)")
    ap.add_argument("--once", action="store_true", help="push once and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the body and send nothing")
    ap.add_argument("--only", choices=["claude", "codex"], help="push just one assistant")
    ap.add_argument("--prices", metavar="FILE",
                    help='JSON of extra or changed prices, e.g. {"gpt-6-new": {"in": 1, "out": 4, "cache_read": 0.1}} '
                         '(USD per 1M tokens)')
    ap.add_argument("--token-file", default="~/.monitor-buddy-usage-token")
    ap.add_argument("--claude-dir", default="~/.claude/projects")
    ap.add_argument("--codex-dir", default="~/.codex/sessions")
    args = ap.parse_args(argv)
    if args.interval < 10:
        ap.error("--interval must be at least 10 seconds")

    if bool(args.host) == bool(args.serial) and not args.dry_run:
        ap.error("give the Buddy's address, or --serial PORT, not both")
    prices = dict(PRICES)
    if args.prices:
        try:
            prices.update(json.loads(Path(args.prices).expanduser().read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            ap.error(f"--prices: {e}")
    host = args.host or ""
    host = host if ":" in host else f"{host}:{DEFAULT_PORT}"
    base = "http://" + host
    claude_root = Path(args.claude_dir).expanduser()
    codex_root = Path(args.codex_dir).expanduser()

    token = None
    while True:
        body = build_body(args.only, dt.date.today(), claude_root, codex_root, prices)
        if args.dry_run:
            print(json.dumps(body, indent=2))
            return 0
        if args.serial:
            ok, err = push_serial(args.serial, body)
            if ok:
                print(time.strftime("%H:%M:%S"), "pushed", json.dumps(body))
            else:
                print(f"the Buddy on {args.serial} did not accept it: {err}", file=sys.stderr)
            if args.once:
                return 0 if ok else 1
            time.sleep(args.interval)
            continue
        if token is None:
            token = load_token(args.token_file)
        try:
            status, reply = push(base, token, body)
        except (urllib.error.URLError, OSError) as e:
            print(f"cannot reach the Buddy at {base}: {getattr(e, 'reason', e)}", file=sys.stderr)
            status, reply = None, None
        if status == 200:
            note = " (paired)" if reply and reply.get("paired") else ""
            print(time.strftime("%H:%M:%S"), "pushed", json.dumps(body), note)
        elif status is not None:
            print(f"the Buddy refused ({status}): {(reply or {}).get('error', 'no detail')}", file=sys.stderr)
            if status in (401, 403):
                return 1   # a wrong token will not fix itself; do not keep retrying
        if args.once:
            return 0 if status == 200 else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
