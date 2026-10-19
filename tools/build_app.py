#!/usr/bin/env python3
"""Build the desktop app with PyInstaller.

    pip install pyinstaller pyserial
    python tools/build_app.py

Windows: dist/MonitorBuddy.exe (one file).
macOS:   dist/MonitorBuddy.app, and dist/MonitorBuddy.dmg with a drag-to-
         Applications shortcut (needs hdiutil, which is part of macOS).
Linux:   dist/MonitorBuddy (one file).

PyInstaller builds for the system it runs on only, so each system needs its
own build: the "Desktop app" workflow does all three on GitHub. The builds are
not code-signed: Windows SmartScreen and macOS Gatekeeper warn the first time
(see the README for how to open it anyway).
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NAME = "MonitorBuddy"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def build():
    system = platform.system()
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", NAME, "--paths", HERE, "--distpath", ROOT / "dist",
            "--workpath", ROOT / "build" / "pyinstaller", "--specpath", ROOT / "build"]
    if system != "Darwin":
        args.append("--onefile")   # on macOS the .app bundle is the product
    args.append(HERE / "buddy_app.py")
    run(args)

    if system == "Darwin":
        app = ROOT / "dist" / f"{NAME}.app"
        stage = ROOT / "build" / "dmg"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        dmg = ROOT / "dist" / f"{NAME}.dmg"
        dmg.unlink(missing_ok=True)
        run(["hdiutil", "create", "-volname", "Monitor Buddy", "-srcfolder", stage,
             "-ov", "-format", "UDZO", dmg])
        print("built", dmg)
    else:
        exe = ROOT / "dist" / (NAME + (".exe" if system == "Windows" else ""))
        print("built", exe)


if __name__ == "__main__":
    build()
