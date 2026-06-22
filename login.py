"""Step 1: Log in manually, ONCE, using a stealth-tuned real Chrome.

Run:  ./venv/bin/python login.py tiktok
      ./venv/bin/python login.py instagram

Thin CLI shim over uploader.auth.LoginManager.
"""
import sys

from uploader.auth import LoginManager


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "tiktok"
    manager = LoginManager()
    if site not in manager.SITES:
        print(f"Unknown site '{site}'. Choose from: {', '.join(manager.SITES)}")
        sys.exit(1)
    manager.login(site)


if __name__ == "__main__":
    main()
