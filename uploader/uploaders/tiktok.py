"""TikTok Studio upload flow.

Selectors here took live DOM inspection to find and TikTok changes its UI
often — rerun the dev inspectors (uploader/dev) to rediscover when something
breaks.
"""
import time
from pathlib import Path

from .base import VideoUploader

# Climb up to 6 parents and return the first short text — used to label a
# switch by the section it sits in.
_CLIMB_LABEL = r"""el => { let n=el; for(let i=0;i<6&&n;i++){ n=n.parentElement;
    if(!n) break; const t=(n.innerText||'').trim(); if(t&&t.length<80) return t; } return ''; }"""


class TikTokUploader(VideoUploader):
    site = "tiktok"
    upload_url = "https://www.tiktok.com/tiktokstudio/upload"

    def _navigate(self, page):
        # ERR_ABORTED can hit on the first nav of a fresh profile; retry a few times.
        for attempt in range(3):
            try:
                page.goto(self.upload_url, wait_until="domcontentloaded", timeout=45000)
                return
            except Exception as e:
                print(f"nav attempt {attempt + 1} failed ({e}); retrying...", flush=True)
                page.wait_for_timeout(2000)

    def _select_video(self, page, video: Path):
        page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
        page.set_input_files("input[type=file]", str(video))
        print("Video selected, waiting for it to process...", flush=True)
        page.wait_for_timeout(10000)

    def _set_caption(self, page, caption: str):
        try:
            box = page.locator("div[contenteditable=true]").first
            box.click(timeout=15000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(caption)   # insert, not type: instant on long text
            print("Caption inserted.", flush=True)
        except Exception as e:
            print(f"Caption step failed ({e}); edit it by hand.", flush=True)

    def _enable_ai_disclosure(self, page):
        """Expand 'Show more' and switch ON 'AI-generated content'."""
        try:
            more = page.locator("text=Show more")
            if more.count() and more.first.is_visible():
                more.first.click()
                page.wait_for_timeout(1500)

            switches = page.locator("input[role=switch]")
            target_root = None
            for i in range(switches.count()):
                inp = switches.nth(i)
                label = inp.evaluate(_CLIMB_LABEL)
                if label.strip().startswith("AI-generated content"):
                    on = inp.evaluate(   # state lives in the visual thumb, not aria-checked
                        "el => { const r = el.closest('[class*=Switch__root]') || el.parentElement;"
                        " return /checked-true/.test(r.innerHTML); }"
                    )
                    if on:
                        print("AI-generated content already ON.", flush=True)
                        return
                    target_root = inp.evaluate_handle(
                        "el => el.closest('[class*=Switch__root]') || el.parentElement"
                    ).as_element()
                    break

            if not target_root:
                print("AI-generated content switch not found; set it by hand.", flush=True)
                return

            target_root.click()
            page.wait_for_timeout(1500)

            for name in ["Turn on", "Confirm", "OK", "Got it", "Yes", "Continue"]:
                btn = page.get_by_role("button", name=name)
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    print(f"AI disclosure confirmed via '{name}'.", flush=True)
                    break
            print("AI-generated content switched ON.", flush=True)
        except Exception as e:
            print(f"AI toggle failed ({e}); set it by hand.", flush=True)

    def _set_cover(self, page, cover: Path):
        """Open Edit cover, upload the image, confirm."""
        try:
            page.locator("text=Edit cover").first.click(timeout=15000)
            page.wait_for_selector('input[accept*="image"]', state="attached", timeout=15000)
            page.set_input_files('input[accept*="image"]', str(cover))
            print("Cover image uploaded into editor, rendering...", flush=True)
            page.wait_for_timeout(5000)

            for name in ["Confirm", "Save", "Done", "Apply", "Set as cover", "OK"]:
                btn = page.get_by_role("button", name=name)
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    print(f"Cover confirmed via '{name}'.", flush=True)
                    return
            # dump visible modal buttons so we can learn the right label
            names = page.evaluate(
                """() => [...document.querySelectorAll('button')]
                       .filter(b => b.offsetParent)
                       .map(b => (b.innerText||'').trim()).filter(Boolean).slice(0,20)"""
            )
            print(f"No known confirm button. Visible buttons: {names}", flush=True)
            print("Confirm the cover by hand in the window.", flush=True)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Cover step failed ({e}); set it by hand in the window.", flush=True)

    # Text that confirms a post went through.
    _SUCCESS_TEXTS = ["being uploaded", "Manage posts", "uploaded to TikTok",
                      "View profile", "Upload another"]
    # The "Continue to post?" safety-check dialog ("We're still checking your
    # video...") — its confirm button. Exact match so we don't hit the main Post.
    _CONFIRM_NAMES = ["Post now", "Post anyway"]

    def _post(self, page) -> bool:
        if not self.settings.auto_post:
            print("\nReady. Review in the Chrome window, then click Post.", flush=True)
            print("Watching for a confirmed post for 2 minutes...", flush=True)
            return self._wait_for_success(page, 120000)

        # TikTok keeps the Post button DISABLED until the video finishes
        # uploading/processing. Clicking too early does nothing, then closing the
        # tab pops a "Leave site?" prompt and the draft is lost — so wait for it.
        if not self._wait_post_enabled(page, 180000):
            print("Post button never enabled (video still processing?); not posting.", flush=True)
            return self._wait_for_success(page, 30000)
        page.get_by_role("button", name="Post", exact=True).first.click()
        print("Clicked Post; handling the 'Continue to post?' check if it appears...", flush=True)
        # the safety-check dialog can pop a few seconds later, so watch for it
        # throughout the wait and click "Post now".
        return self._wait_for_success(page, 120000, handle_confirm=True)

    @staticmethod
    def _wait_post_enabled(page, timeout_ms: int) -> bool:
        """Wait until a visible, non-disabled 'Post' button exists."""
        try:
            page.wait_for_function(
                """() => {
                    const b = [...document.querySelectorAll('button')]
                        .find(x => (x.innerText || '').trim() === 'Post');
                    return !!b && !b.disabled
                        && b.getAttribute('aria-disabled') !== 'true'
                        && b.offsetParent !== null;
                }""",
                timeout=timeout_ms,
            )
            return True
        except Exception:
            return False

    def _click_confirm(self, page):
        """Click 'Post now' on the 'Continue to post?' safety-check dialog."""
        for name in self._CONFIRM_NAMES:
            b = page.get_by_role("button", name=name, exact=True)
            if b.count() and b.first.is_visible():
                b.first.click()
                print(f"Safety-check dialog: clicked '{name}'.", flush=True)
                return True
        return False

    def _wait_for_success(self, page, timeout_ms: int, handle_confirm: bool = False) -> bool:
        """True once TikTok confirms the post (auto OR manual click). Detected by
        redirect to the content manager or a success dialog. When handle_confirm
        is set, also clicks 'Post now' on the safety-check dialog as it appears."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                if "tiktokstudio/content" in page.url:
                    return True
                for txt in self._SUCCESS_TEXTS:
                    if page.get_by_text(txt, exact=False).count():
                        return True
                if handle_confirm:
                    self._click_confirm(page)
            except Exception:
                pass
            page.wait_for_timeout(1500)
        return False
