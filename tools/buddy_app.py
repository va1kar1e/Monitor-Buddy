#!/usr/bin/env python3
"""Monitor Buddy desktop app: set the status page and push Claude / Codex usage.

    python tools/buddy_app.py

A small window for what tools/status_push.py and tools/usage_push.py do on the
command line: pick the USB port (or enter the Buddy's Wi-Fi address), click Free
/ Busy / In a meeting, and optionally let the app push your Claude Code and Codex
token usage every minute. Built into MonitorBuddy.exe (Windows) and a .dmg
(macOS) by tools/build_app.py and the "Desktop app" workflow.

Needs pyserial for USB:  pip install pyserial
Settings are kept in ~/.monitor-buddy-app.json.
"""
import datetime as dt
import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import usage_push as up

SETTINGS_PATH = Path("~/.monitor-buddy-app.json").expanduser()
DEFAULTS = {"mode": "usb", "port": "", "host": "", "interval": 60, "auto_usage": False}

# CP AXTRA palette.
BLUE, YELLOW, GREEN, RED = "#306FC7", "#F6C24A", "#43938F", "#DA3832"
STATES = [("free", "Free", GREEN, "white"), ("busy", "Busy", RED, "white"),
          ("meeting", "In a meeting", YELLOW, "black")]
ESPRESSIF_VID = 0x303A   # the S3's native USB port


def short_tokens(n):
    """4812 -> '4.8k', 76217 -> '76.2k', 150000 -> '150k' (the Buddy's page format)."""
    n = float(n)
    if n < 1000:
        return str(int(n))
    for unit in "kMBT":
        n /= 1000
        if n < 1000 or unit == "T":
            return f"{int(n * 10) / 10:.1f}{unit}" if n < 100 else f"{int(n)}{unit}"


def summary(body):
    """One line for the window: 'Claude 76k / $3.88   Codex 0 / $0.00'."""
    parts = []
    for name in ("claude", "codex"):
        t = body.get(name)
        if t:
            parts.append(f"{name.title()} {short_tokens(t['today'])} / ${t.get('today_usd', 0):.2f}")
    return "   ".join(parts)


def list_ports():
    """[(device, label, looks_like_a_buddy)]; empty when pyserial is missing."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        buddy = p.vid == ESPRESSIF_VID
        out.append((p.device, f"{p.device}  {p.description}" + ("  (Buddy?)" if buddy else ""), buddy))
    return out


class Controller:
    """Everything the window does that is not drawing. One send at a time: a
    serial port cannot be shared, and two pushes at once would only confuse
    the Buddy."""

    def __init__(self, settings_path=SETTINGS_PATH):
        self.path = Path(settings_path)
        self.settings = dict(DEFAULTS)
        try:
            self.settings.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.lock = threading.Lock()

    def save(self):
        try:
            self.path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass

    def target_problem(self):
        """Why we cannot send yet, or None."""
        if self.settings["mode"] == "usb" and not self.settings["port"]:
            return "Pick the Buddy's USB port first."
        if self.settings["mode"] == "wifi" and not self.settings["host"].strip():
            return "Enter the Buddy's Wi-Fi address first."
        return None

    def _send(self, body, command, path):
        """(ok, message) for one body over the chosen transport."""
        problem = self.target_problem()
        if problem:
            return False, problem
        s = self.settings
        if s["mode"] == "usb":
            ok, err = up.push_serial(s["port"], body, command=command)
            return ok, "" if ok else err
        host = s["host"].strip()
        host = host if ":" in host else f"{host}:{up.DEFAULT_PORT}"
        try:
            status, reply = up.push("http://" + host, up.load_token("~/.monitor-buddy-usage-token"), body, path=path)
        except (OSError, ValueError) as e:
            return False, f"cannot reach {host}: {getattr(e, 'reason', e)}"
        if status == 200:
            return True, ""
        return False, f"the Buddy refused ({status}): {(reply or {}).get('error', 'no detail')}"

    def send_status(self, state):
        with self.lock:
            return self._send({"state": state}, "STATUS", "/status")

    def send_usage(self):
        """(ok, message, body)."""
        problem = self.target_problem()
        if problem:
            return False, problem, {}
        body = up.build_body(None, dt.date.today(), Path("~/.claude/projects").expanduser(),
                             Path("~/.codex/sessions").expanduser())
        with self.lock:
            ok, msg = self._send(body, "USAGE", "/usage")
        return ok, msg, body


class App:
    def __init__(self, root, controller):
        self.root, self.ctl = root, controller
        self.events = queue.Queue()
        self.current = None          # the status last sent successfully
        self.tick_id = None          # the pending usage_tick, so there is only ever one
        self.buttons = {}
        self.port_map = {}           # combobox label -> device
        root.title("Monitor Buddy")
        root.minsize(440, 520)
        self.build()
        self.refresh_ports()
        self.root.after(150, self.drain)
        if self.ctl.settings["auto_usage"]:
            self.root.after(500, self.usage_tick)

    # ── layout ────────────────────────────────────────────
    def build(self):
        s = self.ctl.settings
        head = tk.Frame(self.root, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text="Monitor Buddy", bg=BLUE, fg="white",
                 font=("Helvetica", 18, "bold")).pack(anchor="w", padx=16, pady=12)

        body = ttk.Frame(self.root, padding=16)
        body.pack(fill="both", expand=True)

        # Connection
        conn = ttk.LabelFrame(body, text="Connection", padding=10)
        conn.pack(fill="x")
        self.mode = tk.StringVar(value=s["mode"])
        ttk.Radiobutton(conn, text="USB cable", variable=self.mode, value="usb",
                        command=self.on_mode).grid(row=0, column=0, sticky="w")
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(conn, textvariable=self.port, state="readonly", width=34)
        self.port_box.grid(row=0, column=1, padx=8, sticky="we")
        self.port_box.bind("<<ComboboxSelected>>", lambda e: self.on_port())
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=2)
        ttk.Radiobutton(conn, text="Wi-Fi", variable=self.mode, value="wifi",
                        command=self.on_mode).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.host = tk.StringVar(value=s["host"])
        self.host_entry = ttk.Entry(conn, textvariable=self.host, width=36)
        self.host_entry.grid(row=1, column=1, padx=8, pady=(8, 0), sticky="we")
        self.host.trace_add("write", lambda *a: self.on_host())
        ttk.Label(conn, text="IP address, e.g. 192.168.1.50").grid(row=1, column=2, pady=(8, 0))
        conn.columnconfigure(1, weight=1)

        # Status
        st = ttk.LabelFrame(body, text="Status", padding=10)
        st.pack(fill="x", pady=(14, 0))
        row = tk.Frame(st)
        row.pack(fill="x")
        for i, (key, label, bg, fg) in enumerate(STATES):
            b = tk.Label(row, text=label, bg=bg, fg=fg, font=("Helvetica", 14, "bold"),
                         padx=6, pady=16, cursor="hand2", bd=3, relief="flat")
            b.grid(row=0, column=i, sticky="we", padx=4)
            b.bind("<Button-1>", lambda e, k=key: self.set_status(k))
            row.columnconfigure(i, weight=1, uniform="st")
            self.buttons[key] = b
        self.status_note = ttk.Label(st, text="Tap a button, or tap the Buddy's screen.")
        self.status_note.pack(anchor="w", pady=(8, 0))

        # Usage
        us = ttk.LabelFrame(body, text="Claude and Codex usage", padding=10)
        us.pack(fill="x", pady=(14, 0))
        self.auto = tk.BooleanVar(value=s["auto_usage"])
        ttk.Checkbutton(us, text="Send usage every", variable=self.auto,
                        command=self.on_auto).grid(row=0, column=0, sticky="w")
        self.interval = tk.IntVar(value=int(s["interval"]))
        spin = ttk.Spinbox(us, from_=10, to=3600, increment=10, width=6, textvariable=self.interval,
                           command=self.on_interval)
        spin.grid(row=0, column=1, padx=6)
        spin.bind("<FocusOut>", lambda e: self.on_interval())
        ttk.Label(us, text="seconds").grid(row=0, column=2, sticky="w")
        ttk.Button(us, text="Send now", command=self.send_usage_now).grid(row=0, column=3, padx=(16, 0))
        self.usage_line = ttk.Label(us, text="Nothing sent yet.", wraplength=380)
        self.usage_line.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # Log
        lf = ttk.LabelFrame(body, text="Log", padding=6)
        lf.pack(fill="both", expand=True, pady=(14, 0))
        self.log = tk.Text(lf, height=6, state="disabled", wrap="word", font=("Courier", 10))
        self.log.pack(fill="both", expand=True)

        self.on_mode()

    # ── settings ──────────────────────────────────────────
    def refresh_ports(self):
        ports = list_ports()
        self.port_map = {label: dev for dev, label, _ in ports}
        self.port_box["values"] = list(self.port_map)
        wanted = self.ctl.settings["port"]
        pick = next((l for l, d in self.port_map.items() if d == wanted), None) \
            or next((label for dev, label, buddy in ports if buddy), None)
        if pick:
            self.port.set(pick)
            self.ctl.settings["port"] = self.port_map[pick]
        elif not ports:
            self.port.set("(no serial ports found; is pyserial installed?)")

    def on_port(self):
        self.ctl.settings["port"] = self.port_map.get(self.port.get(), "")
        self.ctl.save()

    def on_host(self):
        self.ctl.settings["host"] = self.host.get()
        self.ctl.save()

    def on_mode(self):
        usb = self.mode.get() == "usb"
        self.ctl.settings["mode"] = self.mode.get()
        self.port_box.configure(state="readonly" if usb else "disabled")
        self.host_entry.configure(state="disabled" if usb else "normal")
        self.ctl.save()

    def on_interval(self):
        try:
            v = max(10, min(3600, int(self.interval.get())))
        except (tk.TclError, ValueError):
            v = 60
        self.interval.set(v)
        self.ctl.settings["interval"] = v
        self.ctl.save()

    def on_auto(self):
        self.ctl.settings["auto_usage"] = bool(self.auto.get())
        self.ctl.save()
        self.usage_tick()   # sends now when ticked; cancels the pending one when not

    # ── actions ───────────────────────────────────────────
    def set_status(self, key):
        problem = self.ctl.target_problem()
        if problem:
            self.say(problem)
            return
        self.say(f"Setting status: {key}...")
        threading.Thread(target=self.status_worker, args=(key,), daemon=True).start()

    def status_worker(self, key):
        ok, msg = self.ctl.send_status(key)
        self.events.put(("status", key, ok, msg))

    def send_usage_now(self):
        problem = self.ctl.target_problem()
        if problem:
            self.say(problem)
            return
        threading.Thread(target=self.usage_worker, daemon=True).start()

    def usage_worker(self):
        ok, msg, body = self.ctl.send_usage()
        self.events.put(("usage", ok, msg, body))

    def usage_tick(self):
        """Sends, then schedules the next one while the box stays ticked."""
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        if not self.auto.get():
            return
        if not self.ctl.target_problem():
            threading.Thread(target=self.usage_worker, daemon=True).start()
        self.tick_id = self.root.after(int(self.interval.get()) * 1000, self.usage_tick)

    # ── results back on the UI thread ─────────────────────
    def drain(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "status":
                    _, key, ok, msg = ev
                    if ok:
                        self.current = key
                        self.say(f"Status is now {dict((k, l) for k, l, _, _ in STATES)[key]}.")
                    else:
                        self.say(f"Could not set the status: {msg}")
                    self.mark()
                else:
                    _, ok, msg, body = ev
                    if ok:
                        self.usage_line.configure(text=f"{time.strftime('%H:%M:%S')}  {summary(body)}")
                        self.say("Usage sent.")
                    else:
                        self.say(f"Usage not sent: {msg}")
        except queue.Empty:
            pass
        self.root.after(150, self.drain)

    def mark(self):
        for key, b in self.buttons.items():
            b.configure(relief="solid" if key == self.current else "flat")

    def say(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main():
    root = tk.Tk()
    App(root, Controller())
    root.mainloop()


if __name__ == "__main__":
    main()
