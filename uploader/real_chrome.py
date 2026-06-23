"""Launch the user's real Google Chrome with a DevTools port, so Playwright can
attach over CDP and drive an already-logged-in, keyring-backed session.

Why this exists: on Linux/KDE, Instagram's session cookies are stored as Chrome
v11 (keyring-encrypted). Only real Chrome — with access to the OS secret service
— can decrypt them, so a Playwright-launched Chrome always lands logged-out.
Attaching to real Chrome over CDP sidesteps that entirely.

Notes baked in:
  * Chrome 136+ refuses remote debugging on the DEFAULT user-data-dir, so we
    point at a dedicated dir (a copy of the trusted profile).
  * connecting external tools over CDP needs --remote-allow-origins.
  * Instagram's cookies are keyring-encrypted ("v11"); Chrome decrypts them via the
    secret-service over the session D-Bus. keyring_env() points XDG_RUNTIME_DIR +
    DBUS_SESSION_BUS_ADDRESS at the user's running bus so the keyring is reachable
    even from a bare environment (e.g. cron). Critical: a Chrome that CAN'T decrypt
    the v11 cookies DROPS them — a keyring-less launch silently destroys the saved
    session. (We tried --password-store=basic / v10 to sidestep the keyring, but a
    fresh login inside this automation/CDP Chrome gets captcha-walled by Instagram,
    so the only reliable session is one *copied in from your real Chrome* via
    init_instagram_profile.sh — and those are v11. Hence the keyring route.)
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def keyring_env() -> dict:
    """A copy of os.environ with XDG_RUNTIME_DIR + DBUS_SESSION_BUS_ADDRESS filled
    in (pointing at the user's session bus) if absent, so the launched Chrome can
    reach the keyring and decrypt — not drop — Instagram's v11 cookies, even when
    the caller's environment lacks them (e.g. cron)."""
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    return env


def chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Google Chrome not found on PATH")


def launch_with_cdp(user_data_dir: Path, port: int = 9222, url: str | None = None,
                    wait_seconds: int = 25) -> str:
    """Start real Chrome on `user_data_dir` with remote debugging; return the
    base CDP URL once the endpoint is reachable."""
    args = [
        chrome_binary(),
        f"--user-data-dir={Path(user_data_dir).resolve()}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
    ]
    if url:
        args.append(url)
    subprocess.Popen(args, env=keyring_env(),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as r:
                if r.status == 200:
                    json.load(r)  # ensure it's the DevTools JSON
                    return f"http://127.0.0.1:{port}"
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Chrome DevTools endpoint not ready on port {port}")
