#!/usr/bin/env python3
"""Mouse jiggler for the Monitor Buddy desktop app: nudges the pointer now and then
so the computer does not go idle (screen saver, lock screen, "away" status).

Two styles:
  steady  the same small move every `interval` seconds, left then back right.
  random  a random move of up to `distance` pixels in any direction, at random
          times between 0.5x and 1.5x `interval`.

Either way the pointer goes out and comes back, so it ends where it started. While
you are using the mouse yourself (it is not where the jiggler left it) the nudge is
skipped: your own movement already counts as activity.

No extra packages. Windows uses user32, macOS uses CoreGraphics through ctypes (the
app needs Accessibility permission: System Settings > Privacy & Security >
Accessibility), Linux needs `xdotool` on an X11 session.
"""
import math
import platform
import random
import shutil
import subprocess
import threading

MODES = ("steady", "random")
INTERVAL_RANGE = (1, 3600)   # seconds
DISTANCE_RANGE = (1, 50)     # pixels


class JigglerError(Exception):
    """The pointer cannot be moved (missing permission or tool)."""


# ── pointer backends: position() -> (x, y), move_to(x, y) ─────────────────
class WindowsBackend:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.user32 = ctypes.windll.user32
        self.point = wintypes.POINT
        self.ctypes = ctypes

    def position(self):
        p = self.point()
        self.user32.GetCursorPos(self.ctypes.byref(p))
        return p.x, p.y

    def move_to(self, x, y):
        cx, cy = self.position()
        self.user32.SetCursorPos(int(x), int(y))
        # SetCursorPos alone does not reset Windows' idle timer; a relative
        # mouse_event does (MOUSEEVENTF_MOVE = 1).
        self.user32.mouse_event(0x0001, int(x) - cx, int(y) - cy, 0, 0)


class MacBackend:
    def __init__(self):
        import ctypes
        import ctypes.util

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        self.CGPoint = CGPoint
        self.ctypes = ctypes
        path = ctypes.util.find_library("ApplicationServices")
        if not path:
            raise JigglerError("macOS ApplicationServices was not found")
        lib = ctypes.cdll.LoadLibrary(path)
        lib.CGEventCreate.restype = ctypes.c_void_p
        lib.CGEventCreate.argtypes = [ctypes.c_void_p]
        lib.CGEventGetLocation.restype = CGPoint
        lib.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        lib.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
        lib.CGEventPost.restype = None
        lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        self.lib = lib
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf = cf

    def ask_permission(self):
        """AXIsProcessTrustedWithOptions with the prompt option: macOS shows its own dialog
        (with a button to the right Settings pane) and adds this app to the list there, so
        it does not depend on where a given macOS version keeps the Accessibility switch."""
        ct, cf, lib = self.ctypes, self.cf, self.lib
        key = ct.c_void_p.in_dll(lib, "kAXTrustedCheckOptionPrompt")
        yes = ct.c_void_p.in_dll(cf, "kCFBooleanTrue")
        cf.CFDictionaryCreate.restype = ct.c_void_p
        cf.CFDictionaryCreate.argtypes = [ct.c_void_p, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_void_p),
                                          ct.c_long, ct.c_void_p, ct.c_void_p]
        keys, vals = (ct.c_void_p * 1)(key.value), (ct.c_void_p * 1)(yes.value)
        options = cf.CFDictionaryCreate(None, keys, vals, 1,
                                        ct.addressof(ct.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                                        ct.addressof(ct.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
        lib.AXIsProcessTrustedWithOptions.restype = ct.c_bool
        lib.AXIsProcessTrustedWithOptions.argtypes = [ct.c_void_p]
        trusted = lib.AXIsProcessTrustedWithOptions(options)
        cf.CFRelease(options)
        return trusted

    def check(self):
        if self.lib.AXIsProcessTrusted():
            return
        try:
            self.ask_permission()          # shows macOS's own permission dialog
        except (ValueError, AttributeError, OSError):
            pass                           # the message below still says what to do
        raise JigglerError("macOS has not allowed this app to control the pointer yet. In the dialog that "
                           "just appeared choose Open System Settings and switch Monitor Buddy on (it is "
                           "under Privacy & Security > Accessibility, or Device Control and Data Access on "
                           "newer macOS; if you started the app from Terminal, switch Terminal on). Then "
                           "switch the jiggler on again.")

    def position(self):
        ev = self.lib.CGEventCreate(None)
        p = self.lib.CGEventGetLocation(ev)
        self.cf.CFRelease(ev)
        return p.x, p.y

    def move_to(self, x, y):
        # kCGEventMouseMoved = 5, kCGHIDEventTap = 0. A posted event (unlike a plain
        # warp) also resets the system idle timer.
        ev = self.lib.CGEventCreateMouseEvent(None, 5, self.CGPoint(float(x), float(y)), 0)
        self.lib.CGEventPost(0, ev)
        self.cf.CFRelease(ev)


class XdotoolBackend:
    def __init__(self):
        if not shutil.which("xdotool"):
            raise JigglerError("xdotool is not installed (sudo apt install xdotool); it needs an X11 session")

    def position(self):
        out = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True,
                             timeout=5).stdout
        vals = dict(line.split("=", 1) for line in out.split() if "=" in line)
        return int(vals["X"]), int(vals["Y"])

    def move_to(self, x, y):
        subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))], check=True, timeout=5)


def default_backend():
    system = platform.system()
    if system == "Windows":
        return WindowsBackend()
    if system == "Darwin":
        b = MacBackend()
        b.check()
        return b
    return XdotoolBackend()


# ── the jiggler ───────────────────────────────────────────
def clamp(value, lo_hi):
    return max(lo_hi[0], min(lo_hi[1], value))


class Jiggler:
    """One nudge is step(); start() repeats it on a background thread until stop()."""

    def __init__(self, backend, mode="steady", interval=30, distance=4, rng=None, pause=0.08, on_event=None):
        self.backend = backend
        self.mode = mode if mode in MODES else "steady"
        self.interval = clamp(float(interval), INTERVAL_RANGE)
        self.distance = int(clamp(int(distance), DISTANCE_RANGE))
        self.rng = rng or random.Random()
        self.pause = pause               # seconds between the move out and the move back
        self.on_event = on_event or (lambda text: None)
        self.last_pos = None             # where the pointer was left after our last nudge
        self.nudges = 0
        self.skipped = 0
        self.direction = 1
        self.stopper = threading.Event()
        self.thread = None

    # one nudge: out and back; returns the offset used, or None when skipped
    def step(self):
        here = self.backend.position()
        if self.last_pos is not None and self._moved(here, self.last_pos):
            self.skipped += 1
            self.last_pos = here       # follow the user's pointer, nudge next time
            return None
        dx, dy = self._offset()
        self.backend.move_to(here[0] + dx, here[1] + dy)
        self.stopper.wait(self.pause)
        self.backend.move_to(here[0], here[1])
        self.last_pos = self.backend.position()
        self.nudges += 1
        return dx, dy

    @staticmethod
    def _moved(a, b):
        return abs(a[0] - b[0]) > 1 or abs(a[1] - b[1]) > 1

    def _offset(self):
        d = self.distance
        if self.mode == "steady":
            self.direction = -self.direction
            return self.direction * d, 0
        angle = self.rng.uniform(0, 2 * math.pi)
        radius = self.rng.uniform(max(1, d / 2), d)
        dx, dy = round(math.cos(angle) * radius), round(math.sin(angle) * radius)
        return (dx, dy) if (dx or dy) else (1, 0)

    def next_delay(self):
        if self.mode == "steady":
            return self.interval
        return self.rng.uniform(0.5 * self.interval, 1.5 * self.interval)

    # ── background loop ───────────────────────────────────
    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.running:
            return
        self.stopper.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopper.set()

    def _loop(self):
        self.on_event(f"Mouse jiggler on ({self.mode}, about every {self.interval:g} s, up to {self.distance} px)")
        try:
            while not self.stopper.is_set():
                if self.step() is None:
                    self.on_event("Mouse jiggler: you moved the mouse, skipped")
                if self.stopper.wait(self.next_delay()):
                    break
        except (JigglerError, OSError, subprocess.SubprocessError, KeyError, ValueError) as e:
            self.on_event(f"Mouse jiggler stopped: {e}")
            self.stopper.set()
            return
        self.on_event("Mouse jiggler off")
