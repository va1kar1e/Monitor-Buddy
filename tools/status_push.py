#!/usr/bin/env python3
"""Set the Monitor Buddy's Free / Busy / In a meeting page from this PC.

    python tools/status_push.py --serial COM11 busy
    python tools/status_push.py --serial COM11 meeting
    python tools/status_push.py 192.168.1.50 free          over Wi-Fi

States: free, busy, meeting (also "in a meeting"). The page can also be changed
on the Buddy itself: tap it to step Free -> Busy -> In a meeting. The status is
kept in the Buddy's memory only, so it is Free again after a restart.

Wi-Fi uses the same pairing token as tools/usage_push.py (default
~/.monitor-buddy-usage-token, see that tool for the security note). USB needs
pyserial (pip install pyserial) and no token.

Exit codes: 0 ok, 1 the Buddy refused or could not be reached, 2 bad arguments.
"""
import argparse
import sys
import urllib.error

import usage_push as up

STATES = {"free": "free", "busy": "busy", "meeting": "meeting", "in a meeting": "meeting"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Set the Monitor Buddy's Free / Busy / In a meeting page.")
    ap.add_argument("host", nargs="?", help="the Buddy's IP address or host name, optionally :port")
    ap.add_argument("state", help="free, busy or meeting")
    ap.add_argument("--serial", metavar="PORT", help="use USB serial instead (COM11, /dev/ttyACM0)")
    ap.add_argument("--token-file", default="~/.monitor-buddy-usage-token")
    args = ap.parse_args(argv)

    # With --serial there is no address, so argparse gives the state to "host".
    if args.serial and args.host and args.state:
        ap.error("give the Buddy's address, or --serial PORT, not both")
    word = args.state.strip().lower()
    if word not in STATES:
        ap.error("state must be free, busy or meeting")
    if not args.serial and not args.host:
        ap.error("give the Buddy's address, or --serial PORT")
    body = {"state": STATES[word]}

    if args.serial:
        ok, err = up.push_serial(args.serial, body, command="STATUS")
        if not ok:
            print(f"the Buddy on {args.serial} did not accept it: {err}", file=sys.stderr)
        return 0 if ok else 1

    host = args.host if ":" in args.host else f"{args.host}:{up.DEFAULT_PORT}"
    token = up.load_token(args.token_file)
    try:
        status, reply = up.push("http://" + host, token, body, path="/status")
    except (urllib.error.URLError, OSError) as e:
        print(f"cannot reach the Buddy at {host}: {getattr(e, 'reason', e)}", file=sys.stderr)
        return 1
    if status != 200:
        print(f"the Buddy refused ({status}): {(reply or {}).get('error', 'no detail')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
