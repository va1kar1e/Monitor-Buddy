#!/usr/bin/env python3
"""Monitor Buddy desktop app: every page of the Buddy, its status, and usage push.

    python tools/buddy_app.py

The list on the left has one entry per page the Buddy shows (Face, Clock, Date,
Weather, Stock, GitHub, Claude, Codex, Status, Wi-Fi); click one to see its
numbers. Pick the USB port (or enter the Buddy's Wi-Fi address), click Free /
Busy / In a meeting on the Status page, and optionally let the app push your
Claude Code and Codex token usage every minute. Built into MonitorBuddy.exe
(Windows) and a .dmg (macOS) by tools/build_app.py and the "Desktop app"
workflow.

The Buddy fetches its own weather, GitHub and stock numbers, so this app asks the
same public services with the same settings; "Load from Buddy" (USB) copies the
location, GitHub user and ticker from the Buddy. The Finnhub key is typed in
here and kept in ~/.monitor-buddy-app.json (plain text, like config.h).

Needs pyserial for USB:  pip install pyserial
"""
import datetime as dt
import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import buddy_pages as bp
import usage_push as up

SETTINGS_PATH = Path("~/.monitor-buddy-app.json").expanduser()
DEFAULTS = {"mode": "usb", "port": "", "host": "", "interval": 60, "auto_usage": False,
            "month_limit": 400,
            "lat": "13.7563", "lon": "100.5018", "fahrenheit": False, "mph": False,
            "github_user": "", "ticker": "AAPL", "finnhub_key": ""}

# CP AXTRA palette.
BLUE, YELLOW, GREEN, RED = "#306FC7", "#F6C24A", "#43938F", "#DA3832"
GRAY = "#666666"
STATES = [("free", "Free", GREEN, "white"), ("busy", "Busy", RED, "white"),
          ("meeting", "In a meeting", YELLOW, "black")]
ESPRESSIF_VID = 0x303A   # the S3's native USB port
REFRESH_SECONDS = 600    # weather, stock and GitHub


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
    """One line for the log: 'Claude 76k / $3.88   Codex 0 / $0.00'."""
    parts = []
    for name in ("claude", "codex"):
        t = body.get(name)
        if t:
            parts.append(f"{name.title()} {short_tokens(t['today'])} / ${t.get('today_usd', 0):.2f}")
    return "   ".join(parts)


def limit_text(t):
    """'Limit 42%  Week 17%  resets in 2 h 14 m' from a body entry, '' without limits."""
    parts = []
    if t.get("pct1") is not None:
        parts.append(f"Limit {t['pct1']}%")
    if t.get("pct2") is not None:
        parts.append(f"Week {t['pct2']}%")
    if t.get("reset1") is not None:
        m = t["reset1"]
        parts.append("resets in " + (f"{m} m" if m < 60 else f"{m // 60} h {m % 60} m" if m < 1440
                                     else f"{m // 1440} d {m % 1440 // 60} h"))
    return "  ".join(parts)


def month_text(t):
    """'$126.40 of $400  (32%)' for a body entry, without the limit just '$126.40'."""
    spent = t.get("month_usd", 0)
    limit = t.get("month_limit_usd")
    if not limit:
        return f"${spent:.2f}"
    return f"${spent:.2f} of ${limit:g}  ({spent / limit * 100:.0f}%)"


def month_fraction(t):
    """0..1 for the progress bar (clamped; over the limit still shows full)."""
    limit = t.get("month_limit_usd")
    return min(1.0, t.get("month_usd", 0) / limit) if limit else 0.0


def bar_color(fraction):
    """Blue under 70 %, yellow from 70 %, red from 90 % (the Buddy's bars)."""
    return RED if fraction >= 0.9 else YELLOW if fraction >= 0.7 else BLUE


class Bar(tk.Canvas):
    """A flat progress bar: native ones cannot be coloured on every system."""

    def __init__(self, parent):
        super().__init__(parent, height=12, highlightthickness=0, bg="#DDDDDD")
        self.fraction = 0.0
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, fraction):
        self.fraction = max(0.0, min(1.0, fraction))
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if self.fraction > 0:
            self.create_rectangle(0, 0, max(4, int(w * self.fraction)), 12, width=0,
                                  fill=bar_color(self.fraction))


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
    """Everything the window does that is not drawing. One serial or Wi-Fi
    exchange at a time: a serial port cannot be shared, and two pushes at once
    would only confuse the Buddy."""

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

    def read_usage(self):
        """The usage found in the local Claude Code and Codex logs; sends nothing,
        so it works with no Buddy connected."""
        limit = self.settings.get("month_limit") or None
        return up.build_body(None, dt.date.today(), Path("~/.claude/projects").expanduser(),
                             Path("~/.codex/sessions").expanduser(), month_limit=limit)

    def send_usage(self):
        """(ok, message, body)."""
        body = self.read_usage()
        problem = self.target_problem()
        if problem:
            return False, problem, body
        with self.lock:
            ok, msg = self._send(body, "USAGE", "/usage")
        return ok, msg, body

    # ── the Buddy's own pages ─────────────────────────────
    def wifi_page(self):
        """{'ssid', 'ip', 'rssi', 'connected'} of the Buddy: over USB from its INFO
        reply; over Wi-Fi only the address we were given is known."""
        s = self.settings
        if s["mode"] == "wifi":
            host = s["host"].strip().split(":")[0]
            if not host:
                raise bp.FetchError("Enter the Buddy's Wi-Fi address first.")
            return {"ssid": None, "ip": host, "rssi": None, "connected": True}
        if not s["port"]:
            raise bp.FetchError("Pick the Buddy's USB port first.")
        with self.lock:
            reply, why = up.serial_command(s["port"], "INFO")
        if reply is None or not reply.get("ok"):
            raise bp.FetchError(why or (reply or {}).get("error", "the Buddy did not answer"))
        w = reply.get("wifi") or {}
        return {"ssid": w.get("ssid") or None, "ip": w.get("ip"), "rssi": w.get("rssi"),
                "connected": bool(w.get("connected"))}

    def load_from_buddy(self):
        """Copies location, GitHub user, ticker and units from the Buddy (USB)."""
        s = self.settings
        if s["mode"] != "usb" or not s["port"]:
            raise bp.FetchError("Reading the Buddy's settings needs the USB cable.")
        with self.lock:
            reply, why = up.serial_command(s["port"], "GET")
        if reply is None or not reply.get("ok"):
            raise bp.FetchError(why or (reply or {}).get("error", "the Buddy did not answer"))
        c = reply.get("config") or {}
        for key in ("lat", "lon", "github_user", "ticker"):
            if c.get(key) is not None:
                s[key] = c[key]
        s["fahrenheit"] = c.get("temp_unit") == "fahrenheit"
        s["mph"] = c.get("wind_unit") == "mph"
        self.save()

    def fetch_page(self, key):
        """The data for one network page; raises buddy_pages.FetchError."""
        s = self.settings
        if key == "weather":
            return bp.weather_page(s["lat"], s["lon"], s["fahrenheit"], s["mph"])
        if key == "github":
            return bp.github_page(s["github_user"])
        if key == "stock":
            return bp.stock_page(s["ticker"], s["finnhub_key"])
        if key == "wifi":
            return self.wifi_page()
        raise ValueError(key)


class App:
    def __init__(self, root, controller, autostart=True):
        """autostart=False builds the window without reading logs or the internet (tests)."""
        self.root, self.ctl = root, controller
        self.events = queue.Queue()
        self.current = None          # the status last sent successfully
        self.tick_id = None          # the pending usage_tick, so there is only ever one
        self.buttons = {}
        self.cells = {}
        self.vars = {}               # setting name -> tk variable of its entry
        self.page_frames = {}
        self.page_labels = {}        # (page, field) -> label
        self.port_map = {}           # combobox label -> device
        root.title("Monitor Buddy")
        root.minsize(760, 660)
        self.build()
        self.refresh_ports()
        self.root.after(150, self.drain)
        self.tick_clock()
        if autostart:
            self.refresh_usage()
            self.refresh_network_pages()
            if self.ctl.settings["auto_usage"]:
                self.root.after(500, self.usage_tick)

    # ── layout ────────────────────────────────────────────
    def build(self):
        head = tk.Frame(self.root, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text="Monitor Buddy", bg=BLUE, fg="white",
                 font=("Helvetica", 18, "bold")).pack(anchor="w", padx=16, pady=10)

        top = ttk.Frame(self.root, padding=(16, 12, 16, 0))
        top.pack(fill="x")
        self.build_connection(top)

        mid = ttk.Frame(self.root, padding=(16, 12, 16, 0))
        mid.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(mid, width=14, exportselection=False, activestyle="none",
                                  font=("Helvetica", 12), height=10)
        for _, label in bp.PAGES:
            self.listbox.insert("end", label)
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_page())
        self.stage = ttk.Frame(mid, padding=(16, 0, 0, 0))
        self.stage.pack(side="left", fill="both", expand=True)
        for key, _ in bp.PAGES:
            f = ttk.Frame(self.stage)
            f.grid(row=0, column=0, sticky="nsew")
            self.page_frames[key] = f
            getattr(self, f"page_{key}")(f)
        self.stage.rowconfigure(0, weight=1)
        self.stage.columnconfigure(0, weight=1)

        self.build_usage_sending(ttk.Frame(self.root, padding=(16, 10, 16, 0)))
        lf = ttk.LabelFrame(self.root, text="Log", padding=6)
        lf.pack(fill="x", padx=16, pady=(10, 14))
        self.log = tk.Text(lf, height=4, state="disabled", wrap="word", font=("Courier", 10))
        self.log.pack(fill="x")

        self.on_mode()
        self.listbox.selection_set(1)   # open on the Clock, the first page with numbers
        self.on_page()

    def build_connection(self, parent):
        s = self.ctl.settings
        conn = ttk.LabelFrame(parent, text="Connection", padding=8)
        conn.pack(fill="x")
        self.mode = tk.StringVar(value=s["mode"])
        ttk.Radiobutton(conn, text="USB cable", variable=self.mode, value="usb",
                        command=self.on_mode).grid(row=0, column=0, sticky="w")
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(conn, textvariable=self.port, state="readonly", width=34)
        self.port_box.grid(row=0, column=1, padx=8, sticky="we")
        self.port_box.bind("<<ComboboxSelected>>", lambda e: self.on_port())
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=2)
        ttk.Button(conn, text="Load from Buddy", command=self.load_from_buddy).grid(row=0, column=3, padx=(8, 0))
        ttk.Radiobutton(conn, text="Wi-Fi", variable=self.mode, value="wifi",
                        command=self.on_mode).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.host = tk.StringVar(value=s["host"])
        self.host_entry = ttk.Entry(conn, textvariable=self.host, width=36)
        self.host_entry.grid(row=1, column=1, padx=8, pady=(6, 0), sticky="we")
        self.host.trace_add("write", lambda *a: self.on_host())
        ttk.Label(conn, text="IP address, e.g. 192.168.1.50").grid(row=1, column=2, columnspan=2, pady=(6, 0))
        conn.columnconfigure(1, weight=1)

    def build_usage_sending(self, frame):
        s = self.ctl.settings
        frame.pack(fill="x")
        self.auto = tk.BooleanVar(value=s["auto_usage"])
        ttk.Checkbutton(frame, text="Send Claude / Codex usage every", variable=self.auto,
                        command=self.on_auto).pack(side="left")
        self.interval = tk.IntVar(value=int(s["interval"]))
        spin = ttk.Spinbox(frame, from_=10, to=3600, increment=10, width=6, textvariable=self.interval,
                           command=self.on_interval)
        spin.pack(side="left", padx=6)
        spin.bind("<FocusOut>", lambda e: self.on_interval())
        ttk.Label(frame, text="seconds").pack(side="left")
        ttk.Button(frame, text="Send now", command=self.send_usage_now).pack(side="left", padx=(12, 0))
        ttk.Label(frame, text="Monthly limit $").pack(side="left", padx=(16, 4))
        self.month_limit = tk.IntVar(value=int(s["month_limit"]))
        lim = ttk.Spinbox(frame, from_=0, to=100000, increment=50, width=6, textvariable=self.month_limit,
                          command=self.on_month_limit)
        lim.pack(side="left")
        lim.bind("<FocusOut>", lambda e: self.on_month_limit())

    # ── pages ─────────────────────────────────────────────
    def title(self, frame, text, color=BLUE):
        tk.Label(frame, text=text, fg="white", bg=color, font=("Helvetica", 12, "bold"),
                 padx=10, pady=3).pack(anchor="w")

    def big(self, frame, page, field, size=34, text="-"):
        lab = tk.Label(frame, text=text, font=("Helvetica", size, "bold"), anchor="w")
        lab.pack(anchor="w", pady=(10, 0))
        self.page_labels[(page, field)] = lab
        return lab

    def small(self, frame, page, field, text="", color=GRAY, wrap=460):
        lab = tk.Label(frame, text=text, fg=color, font=("Helvetica", 11), anchor="w", justify="left", wraplength=wrap)
        lab.pack(anchor="w", pady=(4, 0))
        self.page_labels[(page, field)] = lab
        return lab

    def entry(self, parent, setting, width=14, show=None):
        var = tk.StringVar(value=str(self.ctl.settings[setting]))
        self.vars[setting] = var
        ttk.Entry(parent, textvariable=var, width=width, show=show or "").pack(side="left", padx=6)
        var.trace_add("write", lambda *a: self.on_setting(setting, var.get()))

    def entry_row(self, frame, setting, label, width=14, show=None):
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Label(row, text=label).pack(side="left")
        self.entry(row, setting, width, show)
        return row

    def refresh_button(self, frame, keys):
        ttk.Button(frame, text="Refresh", command=lambda: self.refresh_network_pages(keys)).pack(anchor="w", pady=8)

    def page_face(self, f):
        self.title(f, "Face")
        self.big(f, "face", "text", 22, "The animated face")
        self.small(f, "face", "note", "It blinks, glances around and follows the Buddy's tilt. There are no numbers "
                                      "to show: tap it on the Buddy to change its expression.")

    def page_clock(self, f):
        self.title(f, "Clock")
        self.big(f, "clock", "time", 54, "--:--:--")
        self.small(f, "clock", "note", "This computer's time. The Buddy keeps its own clock over NTP, in the time zone "
                                       "saved on it.")

    def page_date(self, f):
        self.title(f, "Date")
        self.big(f, "date", "weekday", 40, "-")
        self.big(f, "date", "day", 26, "-")

    def page_weather(self, f):
        self.title(f, "Weather")
        self.big(f, "weather", "temp", 54, "-")
        self.big(f, "weather", "text", 20, "")
        self.small(f, "weather", "more", "")
        row = self.entry_row(f, "lat", "Latitude", 10)
        ttk.Label(row, text="Longitude").pack(side="left", padx=(12, 0))
        self.entry(row, "lon", 10)
        self.small(f, "weather", "error", "", RED)
        self.refresh_button(f, ["weather"])

    def page_stock(self, f):
        self.title(f, "Stock")
        self.big(f, "stock", "price", 44, "-")
        self.small(f, "stock", "more", "")
        self.entry_row(f, "ticker", "Ticker", 10)
        self.entry_row(f, "finnhub_key", "Finnhub key", 30, show="*")
        self.small(f, "stock", "error", "", RED)
        self.refresh_button(f, ["stock"])

    def page_github(self, f):
        self.title(f, "GitHub")
        self.big(f, "github", "followers", 44, "-")
        self.small(f, "github", "repos", "")
        self.entry_row(f, "github_user", "GitHub user", 24)
        self.small(f, "github", "error", "", RED)
        self.refresh_button(f, ["github"])

    def page_usage(self, f, name, title, color):
        self.title(f, title, color)
        table = tk.Frame(f)
        table.pack(fill="x", pady=(10, 0))
        for c, head in enumerate(("Today", "7 days", "This month")):
            tk.Label(table, text=head, fg=GRAY, font=("Helvetica", 10)).grid(row=0, column=c, sticky="w", padx=4)
        for c, key in enumerate(("today", "week", "month")):
            lab = tk.Label(table, text="-", font=("Helvetica", 14, "bold"), anchor="w")
            lab.grid(row=1, column=c, sticky="we", padx=4, pady=(4, 0))
            self.cells[(name, key)] = lab
            table.columnconfigure(c, weight=1)
        bar = Bar(table)
        bar.grid(row=2, column=0, columnspan=3, sticky="we", padx=4, pady=(6, 0))
        self.cells[(name, "bar")] = bar
        lim = tk.Label(table, text="", fg=GRAY, font=("Helvetica", 10), anchor="w")
        lim.grid(row=3, column=0, columnspan=3, sticky="we", padx=4)
        self.cells[(name, "limit")] = lim
        self.small(f, name, "read", "Reading your logs...")
        self.small(f, name, "note", "Tokens are input + output; $ is an estimate at API list prices.")
        ttk.Button(f, text="Refresh", command=self.refresh_usage).pack(anchor="w", pady=8)

    def page_claude(self, f):
        self.page_usage(f, "claude", "Claude", BLUE)

    def page_codex(self, f):
        self.page_usage(f, "codex", "Codex", GREEN)

    def page_status(self, f):
        self.title(f, "Status")
        row = tk.Frame(f)
        row.pack(fill="x", pady=(14, 0))
        for i, (key, label, bg, fg) in enumerate(STATES):
            b = tk.Label(row, text=label, bg=bg, fg=fg, font=("Helvetica", 14, "bold"),
                         padx=6, pady=22, cursor="hand2", bd=3, relief="flat")
            b.grid(row=0, column=i, sticky="we", padx=4)
            b.bind("<Button-1>", lambda e, k=key: self.set_status(k))
            row.columnconfigure(i, weight=1, uniform="st")
            self.buttons[key] = b
        self.small(f, "status", "note", "Click a button, or tap the Buddy's screen.")

    def page_wifi(self, f):
        self.title(f, "Wi-Fi")
        self.big(f, "wifi", "ssid", 26, "-")
        self.big(f, "wifi", "ip", 34, "-")
        self.small(f, "wifi", "more", "")
        self.small(f, "wifi", "error", "", RED)
        self.refresh_button(f, ["wifi"])

    # ── settings ──────────────────────────────────────────
    def on_page(self):
        sel = self.listbox.curselection()
        if sel:
            key = bp.PAGES[sel[0]][0]
            self.page_frames[key].tkraise()
            if key == "wifi":
                self.refresh_network_pages(["wifi"])

    def on_setting(self, key, value):
        self.ctl.settings[key] = value
        self.ctl.save()

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

    def on_month_limit(self):
        try:
            v = max(0, int(self.month_limit.get()))
        except (tk.TclError, ValueError):
            v = 400
        self.month_limit.set(v)
        self.ctl.settings["month_limit"] = v
        self.ctl.save()
        self.refresh_usage()

    def on_auto(self):
        self.ctl.settings["auto_usage"] = bool(self.auto.get())
        self.ctl.save()
        self.usage_tick()   # sends now when ticked; cancels the pending one when not

    # ── actions ───────────────────────────────────────────
    def tick_clock(self):
        time_s, weekday, day = bp.clock_page(dt.datetime.now())
        self.page_labels[("clock", "time")].configure(text=time_s)
        self.page_labels[("date", "weekday")].configure(text=weekday)
        self.page_labels[("date", "day")].configure(text=day)
        self.root.after(1000, self.tick_clock)

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

    def refresh_usage(self):
        """Reads the logs again and shows them; sends nothing."""
        threading.Thread(target=lambda: self.events.put(("read", self.ctl.read_usage())), daemon=True).start()

    def refresh_network_pages(self, keys=None):
        """Weather, stock, GitHub and Wi-Fi, each in its own thread. Without `keys` it is the
        three that come from the internet, and again every 10 minutes."""
        for key in keys or ("weather", "stock", "github"):
            threading.Thread(target=self.page_worker, args=(key,), daemon=True).start()
        if keys is None:
            self.root.after(REFRESH_SECONDS * 1000, self.refresh_network_pages)

    def page_worker(self, key):
        try:
            self.events.put(("page", key, self.ctl.fetch_page(key), None))
        except bp.FetchError as e:
            self.events.put(("page", key, None, str(e)))
        except Exception as e:   # a page must never take the app down
            self.events.put(("page", key, None, f"{type(e).__name__}: {e}"))

    def load_from_buddy(self):
        def work():
            try:
                self.ctl.load_from_buddy()
                self.events.put(("loaded", None))
            except bp.FetchError as e:
                self.events.put(("loaded", str(e)))
        threading.Thread(target=work, daemon=True).start()

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

    # ── showing results (UI thread) ───────────────────────
    def show_page(self, key, d, error):
        L = self.page_labels
        err = L.get((key, "error"))
        if error:
            if err:
                err.configure(text=error)
            return
        if err:
            err.configure(text="")
        stamp = time.strftime("%H:%M:%S")
        if key == "weather":
            L[("weather", "temp")].configure(text=f"{d['temp']}°{d['unit']}")
            L[("weather", "text")].configure(text=d["text"].title() + ("" if d["is_day"] else "  (night)"))
            L[("weather", "more")].configure(
                text=f"Humidity {d['humidity']}%   Wind {d['wind']} {d['wind_unit']}   (read {stamp})")
        elif key == "github":
            L[("github", "followers")].configure(text=f"{d['followers']:,} followers")
            L[("github", "repos")].configure(text=f"{d['repos']:,} public repos   (read {stamp})")
        elif key == "stock":
            L[("stock", "price")].configure(text=f"${d['price']:,.2f}")
            L[("stock", "more")].configure(
                text=f"{d['change_pct']:+.2f}% today   open {d['open']:,.2f}   "
                     f"high {d['high']:,.2f}   low {d['low']:,.2f}   (read {stamp})")
        elif key == "wifi":
            L[("wifi", "ssid")].configure(text=d["ssid"] or ("(network name: read over USB)" if d["ip"] else "-"))
            L[("wifi", "ip")].configure(text=d["ip"] or "not connected")
            bits = [] if d["connected"] else ["Not connected to Wi-Fi."]
            if d.get("rssi") is not None:
                bits.append(f"Signal {d['rssi']} dBm")
            bits.append(f"read {stamp}")
            L[("wifi", "more")].configure(text="   ".join(bits))

    def show_usage(self, body):
        for name in ("claude", "codex"):
            t = body.get(name)
            if not t:
                continue
            self.cells[(name, "today")].configure(text=f"{short_tokens(t['today'])}   ${t.get('today_usd', 0):.2f}")
            self.cells[(name, "week")].configure(text=f"{short_tokens(t['week'])}   ${t.get('week_usd', 0):.2f}")
            if "month" in t:
                self.cells[(name, "month")].configure(text=f"{short_tokens(t['month'])}   ${t.get('month_usd', 0):.2f}")
                self.cells[(name, "bar")].set(month_fraction(t))
            self.cells[(name, "limit")].configure(
                text="  ".join(x for x in (("Month " + month_text(t)) if t.get("month_limit_usd") else "",
                                           limit_text(t)) if x))
            self.page_labels[(name, "read")].configure(text=f"Read at {time.strftime('%H:%M:%S')}")

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
                elif ev[0] == "read":
                    self.show_usage(ev[1])
                elif ev[0] == "page":
                    self.show_page(*ev[1:])
                elif ev[0] == "loaded":
                    if ev[1]:
                        self.say(ev[1])
                    else:
                        for key in ("lat", "lon", "github_user", "ticker"):
                            self.vars[key].set(str(self.ctl.settings[key]))
                        self.say("Copied location, GitHub user and ticker from the Buddy.")
                        self.refresh_network_pages(["weather", "github", "stock"])
                else:
                    _, ok, msg, body = ev
                    self.show_usage(body)
                    if ok:
                        self.say(f"Usage sent: {summary(body)}")
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
