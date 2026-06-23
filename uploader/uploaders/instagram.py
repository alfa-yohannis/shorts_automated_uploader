"""Instagram Reels upload flow (instagram.com web).

Selectors here were discovered by live DOM inspection against a logged-in
session (uploader/dev/probe_ig_flow.py) on 2026-06-22. IG changes its UI; rerun
that probe to rediscover when something breaks.

Auth note: on Linux/KDE this only works attached to real Chrome over CDP — run
via `upload_instagram.py --chrome`. A Playwright-launched profile lands logged
out (keyring-encrypted v11 cookies). See the README Instagram section.

Verified web flow:
  New post (svg) -> "Post" menu item -> Create-new-post dialog (file input)
  -> "OK" (reels info) -> "Next" (crop) -> Edit screen [optional cover image
  input] -> "Next" -> caption box -> "Share".
"""
import time
from pathlib import Path

from .base import VideoUploader


class InstagramUploader(VideoUploader):
    site = "instagram"
    upload_url = "https://www.instagram.com/"

    _SUCCESS_TEXTS = [
        "has been shared", "reel has been shared", "post has been shared",
        "Your reel", "Your post",
    ]

    # One-off modals IG throws up right after a login (especially "Log in with
    # Facebook"): "Save your login info?", notifications, cookie consent. These
    # cover the New-post button, so we click them away before driving the UI.
    _DISMISS_BUTTONS = [
        "Not now", "Not Now", "Dismiss", "Cancel",
        "Allow all cookies", "Decline optional cookies",
        "Only allow essential cookies",
    ]

    # IG's wizard takes the cover before the caption, so we override the order.
    def _run_steps(self, page, video: Path, caption: str, cover: Path | None) -> bool:
        self._navigate(page)
        self._select_video(page, video)          # ... lands on the Edit screen
        if cover:
            self._set_cover(page, cover)          # cover lives on the Edit screen
        self._click_next(page)                    # Edit -> caption/share screen
        page.wait_for_timeout(2000)
        if caption:
            self._set_caption(page, caption)
        return self._post(page)

    # --- steps ------------------------------------------------------------

    def _navigate(self, page):
        for attempt in range(3):
            try:
                page.goto(self.upload_url, wait_until="domcontentloaded", timeout=45000)
                break
            except Exception as e:
                print(f"nav attempt {attempt + 1} failed ({e}); retrying...", flush=True)
                page.wait_for_timeout(2000)
        page.wait_for_timeout(3500)
        self._dismiss_interstitials(page)
        self._require_logged_in(page)

    def _dismiss_interstitials(self, page):
        """Click away the one-off modals IG shows after a login (Save login info,
        notifications, cookie consent) so they don't cover the New-post button."""
        for _ in range(3):
            clicked = False
            for name in self._DISMISS_BUTTONS:
                try:
                    loc = page.get_by_role("button", name=name, exact=True)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click()
                        print(f"Dismissed interstitial: '{name}'.", flush=True)
                        page.wait_for_timeout(1000)
                        clicked = True
                except Exception:
                    pass
            if not clicked:
                break

    def _require_logged_in(self, page):
        """Raise a clear error if the session is logged out (login form present),
        instead of a cryptic 'New post' timeout later."""
        if page.locator('input[name="username"]').count():
            raise RuntimeError(
                "Instagram session is LOGGED OUT (login form present). Re-login: "
                "./init_instagram_profile.sh (or launch the IG profile and sign in "
                "with Facebook), then retry."
            )

    def _open_create_menu(self, page):
        """Click 'New post' then 'Post'. Robust to a slow home and post-login
        modals: wait for the button, dismissing interstitials and reloading once
        per attempt if it doesn't show."""
        for attempt in range(3):
            self._dismiss_interstitials(page)
            try:
                np = page.locator('svg[aria-label="New post"]').first
                np.wait_for(state="visible", timeout=15000)
                np.click()
                page.wait_for_timeout(1500)
                self._click_text(page, "Post")
                page.wait_for_timeout(2000)
                return
            except Exception as e:
                print(f"'New post' not ready (attempt {attempt + 1}/3: {e}); "
                      "dismissing modals + reloading...", flush=True)
                self._require_logged_in(page)       # raises if logged out
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
        raise RuntimeError("Could not open the Instagram create menu ('New post' never appeared).")

    def _select_video(self, page, video: Path):
        # open the create menu and choose "Post"
        self._open_create_menu(page)
        # the create dialog exposes a hidden file input (accepts video/mp4)
        page.wait_for_selector("input[type=file]", state="attached", timeout=20000)
        page.set_input_files("input[type=file]", str(video))
        print("Video selected, waiting for it to process...", flush=True)
        page.wait_for_timeout(7000)
        # "Video posts are now shared as reels" info dialog
        if self._click_role(page, "OK"):
            print("Dismissed 'shared as reels' dialog.", flush=True)
            page.wait_for_timeout(1200)
        # crop screen: set the aspect ratio to Original, then Next -> Edit screen
        self._set_aspect_original(page)
        self._click_next(page)
        page.wait_for_timeout(2500)

    def _set_aspect_original(self, page):
        """On the crop screen, open 'Select Crop' (bottom-left) and pick Original."""
        try:
            crop = page.locator('svg[aria-label="Select Crop"]')
            if not crop.count():
                print("Crop control not found; leaving default crop.", flush=True)
                return
            crop.first.click()
            page.wait_for_timeout(1000)
            if self._click_role(page, "Original") or self._click_text(page, "Original"):
                print("Aspect ratio set to Original.", flush=True)
                page.wait_for_timeout(800)
            else:
                print("'Original' option not found; leaving default crop.", flush=True)
        except Exception as e:
            print(f"Aspect step failed ({e}); leaving default crop.", flush=True)

    def _set_cover(self, page, cover: Path):
        """On the Edit screen, set the reel cover via the 'Select From Computer'
        button (top-right, below Next); fall back to the hidden image input."""
        try:
            btn = page.get_by_role("button", name="Select From Computer")
            if btn.count() and btn.first.is_visible():
                with page.expect_file_chooser() as fc:
                    btn.first.click()
                fc.value.set_files(str(cover))
                print("Cover image uploaded (Select From Computer).", flush=True)
                page.wait_for_timeout(2500)
                return
            inp = page.locator('input[accept="image/jpeg,image/png"]')
            if not inp.count():
                inp = page.locator('input[accept*="image"]')
            if inp.count():
                inp.first.set_input_files(str(cover))
                print("Cover image uploaded (input fallback).", flush=True)
                page.wait_for_timeout(2500)
            else:
                print("Cover control not found; Instagram will use a video frame.", flush=True)
        except Exception as e:
            print(f"Cover step failed ({e}); set it by hand.", flush=True)

    def _set_caption(self, page, caption: str):
        try:
            box = page.locator('div[aria-label="Write a caption..."]')
            if not (box.count() and box.first.is_visible()):
                box = page.locator('[contenteditable=true][aria-label*="caption" i], '
                                   'textarea[aria-label*="caption" i]')
            if box.count() and box.first.is_visible():
                box.first.click(timeout=15000)
                page.keyboard.insert_text(caption)
                print("Caption inserted.", flush=True)
            else:
                print("Caption box not found; type it by hand.", flush=True)
        except Exception as e:
            print(f"Caption step failed ({e}); edit it by hand.", flush=True)

    def _enable_ai_disclosure(self, page):
        # Not part of IG's web composer; _run_steps doesn't call this, but the
        # abstract base requires it. No-op.
        pass

    def _post(self, page) -> bool:
        if self.settings.auto_post:
            if self._click_share(page):
                print("Clicked Share; waiting for confirmation...", flush=True)
                return self._wait_for_success(page, 120000)
            print("Share button not found; share it by hand.", flush=True)
            return self._wait_for_success(page, 120000)
        print("\nReady. Review in the Chrome window, then click Share.", flush=True)
        print("Watching for a confirmed share for 2 minutes...", flush=True)
        return self._wait_for_success(page, 120000)

    # --- helpers ----------------------------------------------------------

    def _click_next(self, page):
        if not self._click_role(page, "Next"):
            self._click_text(page, "Next")

    def _wait_for_success(self, page, timeout_ms: int) -> bool:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                for txt in self._SUCCESS_TEXTS:
                    if page.get_by_text(txt, exact=False).count():
                        return True
            except Exception:
                pass
            page.wait_for_timeout(1500)
        return False

    @staticmethod
    def _click_text(page, text: str, exact: bool = True) -> bool:
        loc = page.get_by_text(text, exact=exact)
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            return True
        return False

    @staticmethod
    def _click_role(page, name: str, exact: bool = False) -> bool:
        loc = page.get_by_role("button", name=name, exact=exact)
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            return True
        return False

    @staticmethod
    def _click_share(page) -> bool:
        """Click the final Share button. EXACT match + dialog scope so we never
        hit 'Share to' / 'Share to Facebook' on the same screen."""
        scopes = []
        dialog = page.get_by_role("dialog")
        if dialog.count():
            scopes.append(dialog.last)
        scopes.append(page)
        for scope in scopes:
            for role in ("button", "link"):
                loc = scope.get_by_role(role, name="Share", exact=True)
                if loc.count() and loc.first.is_visible():
                    loc.first.click()
                    return True
        return False
