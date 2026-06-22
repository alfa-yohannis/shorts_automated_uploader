"""One-time manual login into a stealth-tuned real Chrome.

A real Chrome window opens with a persistent profile. The human logs in by
hand (2FA / captcha ok); this polls for the login cookie and exits once it
appears, leaving the session inside profiles/<site>/.
"""
import time

from .browser import StealthBrowser
from .config import Settings


class LoginManager:
    """Drives the manual-login flow for a supported site."""

    SITES = {
        "tiktok": {"url": "https://www.tiktok.com/login", "cookie": "sessionid"},
        "instagram": {"url": "https://www.instagram.com/accounts/login/", "cookie": "sessionid"},
    }

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def login(self, site: str, timeout_seconds: int = 600) -> bool:
        if site not in self.SITES:
            raise ValueError(
                f"Unknown site '{site}'. Choose from: {', '.join(self.SITES)}"
            )
        cfg = self.SITES[site]

        with StealthBrowser(site, self.settings.profiles_dir) as browser:
            page = browser.new_page()
            page.goto(cfg["url"])

            print("=" * 60)
            print(f"  Real Chrome open at {site}. Log in by hand (2FA/captcha ok).")
            print(f"  Watching for the '{cfg['cookie']}' cookie...")
            print("=" * 60, flush=True)

            logged_in = self._wait_for_cookie(browser, cfg["cookie"], timeout_seconds)

            if logged_in:
                time.sleep(3)  # let all auth cookies settle into the profile
                print(f"LOGIN DETECTED. Saved in profiles/{site}/", flush=True)
            else:
                print("Timed out waiting for login.", flush=True)
            return logged_in

    @staticmethod
    def _wait_for_cookie(browser: StealthBrowser, cookie: str, timeout_seconds: int) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            names = {c["name"] for c in browser.context.cookies()}
            if cookie in names:
                return True
            time.sleep(2)
        return False
