"""YouTube Studio upload flow (studio.youtube.com).

Selectors target Studio's upload wizard (Polymer ``ytcp-*`` / ``tp-yt-*`` custom
elements, all in the light DOM so plain CSS reaches them). YouTube changes Studio
periodically — rerun ``uploader.dev.inspect_youtube`` to rediscover when a step
breaks.

Auth: Google bot-detects fresh logins hard, so the reliable path is to drive your
real, already-logged-in Chrome — a persistent stealth profile (``login.py
youtube``) or attach-to-real-Chrome over CDP (``upload_youtube.py --chrome``),
exactly like Instagram. profiles/youtube/ holds the session.

Unlike TikTok/IG this also takes LANDSCAPE videos, not just portrait Shorts.

Caption .txt layout (markers on their own lines) drives the metadata:
    TITLE
    <the title>                 -> video title (<=100 chars)
    DESCRIPTION
    <body + #hashtags>          -> description
    KEYWORDS
    <comma, separated, list>    -> tags

Also set per video: audience = NOT made for kids; video language from the file
suffix (``_en`` -> English, ``_id`` -> Indonesian); recording date = today;
custom thumbnail ONLY for landscape (the web app rejects Short thumbnails);
visibility from settings.yt_visibility (default public).

Wizard: upload URL opens the dialog -> pick file -> [Details: title, description,
thumbnail, audience, Show more: tags/language/date] -> Next x3 -> Visibility -> Publish.
"""
import random
import re
import time
from datetime import date
from pathlib import Path

from .base import VideoUploader


class YouTubeUploader(VideoUploader):
    site = "youtube"
    upload_url = "https://studio.youtube.com/"   # _navigate builds the channel URL
    enforce_portrait = False                     # YouTube takes landscape too, not just Shorts

    def studio_url(self, suffix: str = "") -> str:
        """This channel's Studio URL (settings.yt_channel_id), else generic Studio."""
        cid = self.settings.yt_channel_id
        return f"https://studio.youtube.com/channel/{cid}{suffix}" if cid else self.upload_url

    # --- selectors (comma-separated = try each in order) ---
    _CREATE_BTN = "ytcp-button#create-icon, #create-icon, button[aria-label='Create']"
    _UPLOAD_ITEM = "Upload videos"                       # menu item text
    _FILE_INPUT = "input[type=file]"
    _TITLE_BOX = "#title-textarea #textbox, ytcp-social-suggestions-textbox#title-textarea #textbox"
    _DESC_BOX = "#description-textarea #textbox, ytcp-social-suggestions-textbox#description-textarea #textbox"
    _THUMB_INPUT = "input#file-loader, input[type=file][accept*='image']"
    _NEXT_BTN = "ytcp-button#next-button, #next-button"
    _DONE_BTN = "ytcp-button#done-button, #done-button"
    _MFK_NO = "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']"
    _MFK_YES = "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_MFK']"
    _ALTERED_NO = "tp-yt-paper-radio-button[name='VIDEO_HAS_ALTERED_CONTENT_NO']"
    _RELATED_ADD = ("ytcp-video-metadata-related-video ytcp-button, "
                    "#related-video ytcp-button, #related-video-container ytcp-button, "
                    "ytcp-button[aria-label*='related' i]")
    _PICK_DIALOG = "ytcp-video-pick-dialog"
    _PICK_CARD = "ytcp-video-pick-dialog ytcp-entity-card"
    _PICK_CONFIRM = ("ytcp-video-pick-dialog ytcp-button#select-button, "
                     "ytcp-video-pick-dialog #done-button, ytcp-video-pick-dialog #select-button")
    _SHOW_MORE = "ytcp-button#toggle-button, #toggle-button"
    _TAGS_INPUT = ("#tags-container #text-input, ytcp-form-input-container#tags-wrapper input, "
                   "input[aria-label*='tag' i]")
    _DROPDOWN = "ytcp-text-dropdown-trigger, ytcp-dropdown-trigger"   # generic Studio dropdown
    _MENU_ITEM = "tp-yt-paper-item, ytcp-text-menu tp-yt-paper-item, #text-item"
    _DATE_TRIGGER = "ytcp-text-dropdown-trigger#recorded-date, #recorded-date"
    _DATE_INPUT = "ytcp-date-picker input"   # scoped to the picker (NOT the Video location field)
    _LICENSE_OPTION = {"creative_commons": "Creative Commons", "standard": "Standard YouTube License"}
    _VIS_RADIO = {"public": "PUBLIC", "unlisted": "UNLISTED", "private": "PRIVATE"}

    # Only TRUE post-publish confirmations — NOT "processing"/"uploading" text, which
    # shows during the normal upload and would falsely report success before Publish.
    _SUCCESS_TEXTS = [
        "Video published", "Short published", "is now live", "published to your channel",
    ]

    # YouTube's wizard handles cover/audience/visibility itself, so override order.
    def _run_steps(self, page, video: Path, caption: str, cover: Path | None) -> bool:
        self._navigate(page)
        self._select_video(page, video)
        tags = []
        if caption:
            self._set_caption(page, caption)            # title + description
            tags = self._parse_caption(caption)[2]
        # custom thumbnail: the web app only accepts it for LANDSCAPE, not Shorts
        if cover and not self.is_portrait(video):
            self._set_cover(page, cover)
        elif cover:
            print("Portrait video — custom thumbnail not supported on the web; skipping.", flush=True)
        self._set_made_for_kids(page)
        self._expand_show_more(page)                            # reveals altered-content + tags/lang/date/license
        self._set_altered_content(page)                         # AI/altered-content disclosure -> No
        self._set_advanced(page, tags, self._lang_for(video))   # tags, language, recording date, license
        if self.is_portrait(video):                             # Shorts: link a related video
            self._set_related_video(page, video)
        return self._post(page)

    def _expand_show_more(self, page):
        """Click 'Show more' to reveal the rest of the Details form — the altered-
        content (AI) disclosure, tags, language, recording date and license all live
        below it. Idempotent: if tags are already visible, it's already expanded."""
        if page.locator(self._TAGS_INPUT).count():
            return
        if self._click_first(page, self._SHOW_MORE, timeout=6000) or self._click_text(page, "Show more"):
            page.wait_for_timeout(1500)
        else:
            print("'Show more' not found; the AI/advanced fields stay hidden.", flush=True)

    # --- steps ------------------------------------------------------------

    def _navigate(self, page):
        # The channel's upload URL opens the upload dialog directly (no Create click,
        # no channel picker). ?d=ud is Studio's "open upload dialog" hint.
        url = self.studio_url("/videos/upload?d=ud")
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                break
            except Exception as e:
                print(f"nav attempt {attempt + 1} failed ({e}); retrying...", flush=True)
                page.wait_for_timeout(2000)
        page.wait_for_timeout(4000)   # Studio is slow to hydrate

    def _select_video(self, page, video: Path):
        # The upload URL usually auto-opens the dialog (file input present). If it
        # isn't there, open it the long way: Create -> "Upload videos".
        try:
            page.wait_for_selector(self._FILE_INPUT, state="attached", timeout=8000)
        except Exception:
            print("Upload dialog not auto-open; opening via Create -> Upload videos.", flush=True)
            if self._click_first(page, self._CREATE_BTN, timeout=20000):
                page.wait_for_timeout(1000)
                self._click_text(page, self._UPLOAD_ITEM)
                page.wait_for_timeout(1500)
            page.wait_for_selector(self._FILE_INPUT, state="attached", timeout=30000)
        page.set_input_files(self._FILE_INPUT, str(video))
        print("Video selected, uploading/processing...", flush=True)
        # wait for the Details dialog (title box) to render
        try:
            page.wait_for_selector(self._TITLE_BOX.split(",")[0].strip(),
                                   state="visible", timeout=90000)
        except Exception:
            page.wait_for_timeout(8000)

    def _set_caption(self, page, caption: str):
        """Set title + description parsed from the TITLE/DESCRIPTION/KEYWORDS layout."""
        title, desc, _ = self._parse_caption(caption)
        self._fill_box(page, self._TITLE_BOX, title, "Title")
        self._fill_box(page, self._DESC_BOX, desc, "Description")

    def _set_cover(self, page, cover: Path):
        """Custom thumbnail (landscape only — callers gate portrait out)."""
        try:
            inp = page.locator(self._THUMB_INPUT)
            if inp.count():
                inp.first.set_input_files(str(cover))
                print("Thumbnail uploaded.", flush=True)
                page.wait_for_timeout(3000)
            else:
                print("Thumbnail input not found; skipping.", flush=True)
        except Exception as e:
            print(f"Thumbnail step skipped ({e}).", flush=True)

    def _set_made_for_kids(self, page):
        """REQUIRED: pick the audience radio, else Publish stays disabled."""
        sel = self._MFK_YES if self.settings.yt_made_for_kids else self._MFK_NO
        try:
            r = page.locator(sel)
            if r.count():
                r.first.scroll_into_view_if_needed(timeout=5000)
                r.first.click(timeout=10000)
                kind = "made for kids" if self.settings.yt_made_for_kids else "not made for kids"
                print(f"Audience set: {kind}.", flush=True)
            else:
                print("Audience radio not found; set 'made for kids' by hand.", flush=True)
        except Exception as e:
            print(f"Audience step failed ({e}); set it by hand.", flush=True)

    def _set_altered_content(self, page):
        """REQUIRED: the 'altered / AI content' disclosure -> No (else Next blocks).
        The section lazy-renders, so wait for the radio to appear."""
        # Lives below 'Show more' (expanded just before this) — wait for it to render.
        try:
            page.wait_for_selector(self._ALTERED_NO, state="attached", timeout=10000)
        except Exception:
            print("Altered-content radio not found (Show more not expanded?); skipping.", flush=True)
            return
        try:
            r = page.locator(self._ALTERED_NO).first
            r.scroll_into_view_if_needed(timeout=5000)
            r.click(timeout=10000)
            print("Altered content (AI use): No.", flush=True)
        except Exception as e:
            print(f"Altered-content click failed ({e}); set it by hand.", flush=True)

    def _set_related_video(self, page, video: Path):
        """Shorts only: link a random RELATED video that's also portrait + same
        language (from the other *_portrait_<lang> titles in the folder). The picker
        only lists videos already on the channel, so try a few until one matches."""
        cands = self._related_title_candidates(video)
        if not cands:
            print("No related-video candidate (need another portrait video, same language); skipping.", flush=True)
            return
        if not self._click_first(page, self._RELATED_ADD, timeout=6000):
            try:
                cand = page.evaluate(
                    "() => [...document.querySelectorAll('ytcp-button,ytcp-video-pick-button,button')]"
                    ".filter(b=>b.offsetParent).map(b=>((b.innerText||'').trim().slice(0,16))+' #'+(b.id||'')"
                    "+' @'+((b.closest('[id]')||{}).id||'')).filter(s=>/related|select|add|video/i.test(s)).slice(0,12)")
            except Exception:
                cand = []
            print(f"Related-video 'Add' button not found; candidates: {cand}", flush=True)
            return
        page.wait_for_timeout(1500)
        try:
            inp = page.locator(self._PICK_DIALOG).locator("input").first
            for title in cands[:4]:               # try a few until one is on the channel
                inp.click(timeout=8000)
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.keyboard.insert_text(title)
                page.wait_for_timeout(2200)
                card = page.locator(self._PICK_CARD).first
                if card.count() and card.is_visible():
                    card.click()
                    page.wait_for_timeout(1000)
                    self._click_first(page, self._PICK_CONFIRM, timeout=3000)
                    print(f"Related video set: {title[:45]}", flush=True)
                    return
            print("No related candidate found on the channel; closing picker.", flush=True)
            page.keyboard.press("Escape")
        except Exception as e:
            print(f"Related-video step skipped ({e}).", flush=True)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    @staticmethod
    def _related_title_candidates(video: Path):
        """Shuffled TITLEs from other *_portrait_<lang> .txt in the same folder
        (same language, excluding this video)."""
        p = Path(video)
        stem = p.stem.lower()
        lang = "en" if stem.endswith("_en") else ("id" if stem.endswith("_id") else None)
        if lang is None or "_portrait_" not in stem:
            return []
        cands = []
        for txt in sorted(p.parent.glob(f"*_portrait_{lang}.txt")):
            if txt.stem.lower() == stem:
                continue
            try:
                t = YouTubeUploader._parse_caption(txt.read_text(encoding="utf-8"))[0]
            except Exception:
                continue
            if t and t != "Untitled":
                cands.append(t)
        random.shuffle(cands)
        return cands

    def _set_advanced(self, page, tags, language):
        """Expand 'Show more' and set tags, video language, recording date."""
        if not page.locator(self._TAGS_INPUT).count():
            if not (self._click_first(page, self._SHOW_MORE, timeout=6000)
                    or self._click_text(page, "Show more")):
                print("'Show more' not found; tags/language/date skipped.", flush=True)
                return
            page.wait_for_timeout(1500)
        self._set_tags(page, tags)
        self._set_language(page, language)
        self._set_recording_date(page)
        self._set_license(page)

    def _set_tags(self, page, tags):
        if not tags:
            return
        try:
            box = page.locator(self._TAGS_INPUT)
            if not box.count():
                print("Tags input not found; skipping.", flush=True); return
            box.first.scroll_into_view_if_needed(timeout=5000)
            box.first.click(timeout=8000)
            page.keyboard.insert_text(", ".join(tags)[:480] + ",")   # trailing comma commits the last tag
            page.keyboard.press("Escape")          # close the tag-suggestion overlay (it blocks later dropdowns)
            page.wait_for_timeout(600)
            print(f"Tags set ({len(tags)}).", flush=True)
        except Exception as e:
            print(f"Tags step skipped ({e}).", flush=True)

    def _select_dropdown(self, page, label: str, option: str, exact_option: bool = True) -> bool:
        """Open the Studio dropdown whose trigger contains `label`, click `option`."""
        try:
            trig = page.locator(self._DROPDOWN).filter(has_text=label)
            if not trig.count():
                return False
            trig.first.scroll_into_view_if_needed(timeout=5000)
            trig.first.click(timeout=8000)
            page.wait_for_timeout(1200)            # let the option menu render
            opt = page.get_by_text(option, exact=exact_option)
            if not opt.count():
                opt = page.locator(self._MENU_ITEM).filter(has_text=option)
            if opt.count() and opt.first.is_visible():
                opt.first.click()
                page.wait_for_timeout(500)
                return True
            page.keyboard.press("Escape")
            return False
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _set_language(self, page, language):
        """Open the 'Video language' dropdown (a flat ~240-item list, no search) and
        click the exact-match item. After the tags interaction the trigger sometimes
        needs a couple of clicks to actually open the menu, so retry until a known
        language item ('Abkhazian') is present, then click the wanted language."""
        if not language:
            return
        try:
            trig = page.locator(self._DROPDOWN).filter(has_text="Video language")
            if not trig.count():
                print("Language dropdown not found; set it by hand.", flush=True); return
            for _ in range(4):
                ab = page.get_by_text("Abkhazian", exact=True)
                if ab.count() and ab.first.is_visible():
                    break                                 # menu genuinely OPEN (items keep
                trig.first.scroll_into_view_if_needed(timeout=5000)   # living in the DOM when
                trig.first.click(timeout=8000)                        # closed, so count() lies)
                page.wait_for_timeout(1800)
            # exact-text item, so "English" doesn't match "English (UK)" etc. It's in
            # the DOM but usually scrolled off-screen — scroll it in, then click.
            opt = page.locator("tp-yt-paper-item").filter(
                has_text=re.compile(rf"^\s*{re.escape(language)}\s*$"))
            if opt.count():
                # The item is in the DOM but clipped below the fold of the listbox's
                # own scroll container, so scroll THAT container to it (page-level
                # scroll_into_view doesn't move it), then click.
                opt.first.evaluate("""el => {
                  let p = el.parentElement;
                  while (p && p.scrollHeight <= p.clientHeight + 2) p = p.parentElement;
                  if (p) {
                    const er = el.getBoundingClientRect(), pr = p.getBoundingClientRect();
                    p.scrollTop += (er.top - pr.top) - pr.height / 2 + er.height / 2;
                  } else { el.scrollIntoView({block: 'center'}); }
                }""")
                page.wait_for_timeout(500)
                opt.first.click(timeout=8000)
                print(f"Language set: {language}.", flush=True)
            else:
                print(f"Language '{language}' option not found; set it by hand.", flush=True)
                page.keyboard.press("Escape")
        except Exception as e:
            print(f"Language step skipped ({e}); set it by hand.", flush=True)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    def _set_license(self, page):
        key = (self.settings.yt_license or "standard").lower()
        if key == "standard":
            return   # Standard YouTube License is the default — nothing to do
        want = self._LICENSE_OPTION.get(key, "Creative Commons")
        if self._select_dropdown(page, "License", want, exact_option=False):
            print(f"License set: {want}.", flush=True)
        else:
            print(f"License '{want}' not set; set it by hand.", flush=True)

    def _set_recording_date(self, page):
        try:
            today = date.today()
            trig = page.locator(self._DATE_TRIGGER)
            if not trig.count():
                print("Recording-date control not found; skipping.", flush=True); return
            trig.first.scroll_into_view_if_needed(timeout=5000)
            trig.first.click(timeout=8000)
            page.wait_for_timeout(900)
            inp = page.locator(self._DATE_INPUT)
            if inp.count():
                inp.first.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.keyboard.insert_text(f"{today:%b} {today.day}, {today.year}")   # "Jun 23, 2026"
                page.keyboard.press("Enter")
                print(f"Recording date set: {today.isoformat()}.", flush=True)
            else:
                print("Recording-date input not found; skipping.", flush=True)
                page.keyboard.press("Escape")
        except Exception as e:
            print(f"Recording-date step skipped ({e}).", flush=True)

    def _enable_ai_disclosure(self, page):
        # Abstract base requires it; the YouTube wizard (above) doesn't use it.
        pass

    def _post(self, page) -> bool:
        # Details -> Video elements -> Checks -> Visibility (3 x Next)
        for _ in range(3):
            if not self._click_first(page, self._NEXT_BTN, timeout=15000):
                break
            page.wait_for_timeout(1500)
        self._set_visibility(page)

        if not self.settings.auto_post:
            print("\nReady on the Visibility step (public selected) — saved as a draft. "
                  "Review and Publish by hand when you like (--no-post records nothing).", flush=True)
            return False

        # Publishing while checks are still running pops a strike-risk warning;
        # wait for "Checks complete" first to avoid it.
        self._wait_for_checks(page, 120000)
        if self._click_first(page, self._DONE_BTN, timeout=20000):
            print("Clicked Publish; confirming 'Publish anyway' if prompted...", flush=True)
            page.wait_for_timeout(1500)
            b = page.get_by_role("button", name="Publish anyway", exact=True)
            if b.count() and b.first.is_visible():
                b.first.click()
                print("Confirmed 'Publish anyway'.", flush=True)
        else:
            print("Publish button not found; click it by hand.", flush=True)
        return self._wait_for_success(page, 120000)

    def _wait_for_checks(self, page, timeout_ms: int) -> bool:
        """Wait until upload checks finish ('Checks complete') so publishing doesn't
        trigger YouTube's 'we're still checking your content' strike-risk warning."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                if page.get_by_text("Checks complete", exact=False).count():
                    print("Checks complete.", flush=True)
                    return True
            except Exception:
                pass
            page.wait_for_timeout(2000)
        print("Checks not complete in time; will confirm 'Publish anyway' if prompted.", flush=True)
        return False

    def _set_visibility(self, page):
        name = self._VIS_RADIO.get((self.settings.yt_visibility or "public").lower(), "PUBLIC")
        try:
            r = page.locator(f"tp-yt-paper-radio-button[name='{name}']")
            if r.count():
                r.first.scroll_into_view_if_needed(timeout=5000)
                r.first.click(timeout=10000)
                print(f"Visibility set: {name.lower()}.", flush=True)
            else:
                print(f"Visibility radio '{name}' not found; set it by hand.", flush=True)
        except Exception as e:
            print(f"Visibility step failed ({e}); set it by hand.", flush=True)

    # --- parsing / helpers -----------------------------------------------

    @staticmethod
    def _parse_caption(caption: str):
        """Parse the TITLE / DESCRIPTION / KEYWORDS .txt layout into
        (title<=100, description, [tags]). Falls back to first-line title +
        whole-text description when the markers are absent."""
        buckets = {"TITLE": [], "DESCRIPTION": [], "KEYWORDS": []}
        section = None
        for ln in caption.splitlines():
            key = ln.strip().upper()
            if key in buckets:
                section = key
                continue
            if section:
                buckets[section].append(ln)
        title = " ".join(l.strip() for l in buckets["TITLE"] if l.strip())[:100]
        desc = "\n".join(buckets["DESCRIPTION"]).strip()
        kw = " ".join(l.strip() for l in buckets["KEYWORDS"] if l.strip())
        tags = [t.strip() for t in kw.split(",") if t.strip()]
        if not title:
            first = next((l.strip() for l in caption.splitlines() if l.strip()), "")
            title = first[:100] or "Untitled"
        if not desc:
            desc = caption.strip()
        return title, desc, tags

    @staticmethod
    def _lang_for(video: Path):
        """Video language from the file suffix: _en -> English, _id -> Indonesian."""
        stem = Path(video).stem.lower()
        if stem.endswith("_en"):
            return "English"
        if stem.endswith("_id"):
            return "Indonesian"
        return None

    def _fill_box(self, page, selector_csv: str, text: str, label: str):
        try:
            box = page.locator(selector_csv).first
            box.click(timeout=15000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(text)        # instant on long text, unlike .type()
            print(f"{label} set.", flush=True)
        except Exception as e:
            print(f"{label} step failed ({e}); set it by hand.", flush=True)

    @staticmethod
    def _click_first(page, selector_csv: str, timeout: int = 10000) -> bool:
        """Click the first visible match among comma-separated selectors."""
        deadline = time.time() + timeout / 1000
        selectors = [s.strip() for s in selector_csv.split(",") if s.strip()]
        while time.time() < deadline:
            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click()
                        return True
                except Exception:
                    pass
            page.wait_for_timeout(500)
        return False

    @staticmethod
    def _click_text(page, text: str) -> bool:
        loc = page.get_by_text(text, exact=False)
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            return True
        return False

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
