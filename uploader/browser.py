"""Stealth-tuned real-Chrome launcher, wrapped as a context manager.

Uses your REAL Google Chrome (channel="chrome"), a PERSISTENT profile per
site (so logins stick), strips the automation flags TikTok/Instagram look
for, and applies playwright-stealth patches.

    with StealthBrowser("tiktok", settings.profiles_dir) as browser:
        page = browser.new_page()
        ...
"""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


@dataclass
class Monitor:
    """A screen region the browser window can be placed on."""
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def pick(cls) -> "Monitor":
        """Return the SECOND monitor if present, else the first.
        Falls back to a sane default if xrandr isn't available."""
        try:
            out = subprocess.run(
                ["xrandr", "--listmonitors"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            # lines like:  0: +*eDP-1 1920/293x1080/165+0+0  eDP-1
            mons = []
            for line in out.splitlines():
                m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", line)
                if m:
                    w, h, x, y = map(int, m.groups())
                    mons.append(cls(x, y, w, h))
            if not mons:
                return cls(0, 0, 1920, 1080)
            mons.sort(key=lambda mm: mm.x)   # left-to-right
            return mons[1] if len(mons) > 1 else mons[0]
        except Exception:
            return cls(0, 0, 1920, 1080)


class StealthBrowser:
    """Owns the browser lifecycle for one site.

    Two modes:
      * launch (default) — start our own stealth real-Chrome persistent context.
      * attach (cdp_url) — connect to an already-running Chrome over the DevTools
        protocol and drive it. Used when a site only stays logged-in inside the
        user's real, keyring-backed profile (e.g. Instagram on Linux/KDE).
    """

    STEALTH_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-infobars",
    ]

    def __init__(self, site: str, profiles_dir: Path, headless: bool = False,
                 cdp_url: str | None = None):
        self.site = site
        self.profile_dir = Path(profiles_dir) / site
        self.headless = headless
        self.cdp_url = cdp_url
        self._pw = None
        self._browser = None      # only set in attach mode
        self.context = None

    @property
    def attached(self) -> bool:
        return self.cdp_url is not None

    def __enter__(self) -> "StealthBrowser":
        self._pw = sync_playwright().start()
        if self.attached:
            # connect to the user's real Chrome; reuse its existing context
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
            self.context = (self._browser.contexts[0] if self._browser.contexts
                            else self._browser.new_context())
        else:
            self.context = self._launch()
            Stealth().apply_stealth_sync(self.context)   # webdriver, plugins, etc.
        return self

    def __exit__(self, *exc):
        if self.attached:
            # leave the user's Chrome open & logged in; just drop our connection
            if self._pw is not None:
                self._pw.stop()
            return
        if self.context is not None:
            self.context.close()
        if self._pw is not None:
            self._pw.stop()

    def new_page(self):
        """In attach mode open a fresh tab (don't hijack the user's current one);
        in launch mode reuse the context's first tab."""
        if self.attached:
            return self.context.new_page()
        return self.context.pages[0] if self.context.pages else self.context.new_page()

    def _launch(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        mon = Monitor.pick()
        args = self.STEALTH_ARGS + [
            f"--window-position={mon.x},{mon.y}",   # place on the chosen (2nd) monitor
            f"--window-size={mon.width},{mon.height}",   # fill it -> maximized
        ]
        return self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="chrome",                # real Google Chrome, not bundled Chromium
            headless=self.headless,
            slow_mo=40,
            args=args,
            no_viewport=True,                # page uses the full window size
            ignore_default_args=["--enable-automation"],
        )
