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

Caption .txt layout — positional (preferred, no markers needed):
    <first line>                -> video title (<=100 chars)
    <everything in between>     -> description (body + #hashtags)
    <last line>                 -> keywords (comma-separated tags)

Alternatively, use explicit markers on their own lines:
    TITLE / DESCRIPTION / KEYWORDS

Also set per video: audience = NOT made for kids; video language from
settings.yt_language, else the file suffix (``_en`` -> English, ``_id`` ->
Indonesian); recording date = today; custom thumbnail ONLY for landscape (the web
app rejects Short thumbnails; a cover over YouTube's 2 MB limit is re-encoded to
JPEG first); the playlist titled settings.yt_playlist; visibility from
settings.yt_visibility (default public). The video's youtu.be link is read from the
dialog as soon as the file is picked, printed, and stored in the ledger.

Wizard: upload URL opens the dialog -> pick file -> [Details: title, description,
thumbnail, playlist, audience, Show more: tags/language/date] -> Next x3 ->
Visibility -> Publish.

Delete: ``delete()`` opens the video's Studio edit page -> Options -> Delete ->
ticks "I understand ..." -> confirms, then drops the video from the ledger.
"""
import json
import random
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from ..browser import StealthBrowser
from .base import LoginRequired, UploadFailed, VideoUploader

#: YouTube rejects custom thumbnails larger than 2 MB.
THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024

#: YouTube's public oEmbed endpoint; it answers with a title only for a published
#: public or unlisted video, never for a draft or a private one.
OEMBED_URL = "https://www.youtube.com/oembed?format=json&url="
#: the 11-character id in youtu.be/<id>, watch?v=<id>, shorts/<id>, video/<id>
_ID = r"[0-9A-Za-z_-]{11}"
_ID_IN_LINK = [rf"youtu\.be/({_ID})", rf"[?&]v=({_ID})", rf"/shorts/({_ID})", rf"/video/({_ID})"]


#: youtube.txt headers: the three text blocks, then the upload settings that
#: slides_narrator writes after KEYWORDS (one value line each).
TEXT_HEADERS = ("TITLE", "DESCRIPTION", "KEYWORDS")
SETTING_HEADERS = ("VIDEO", "PLAYLIST", "LANGUAGE", "CATEGORY", "LICENSE", "VISIBILITY",
                   "MADE_FOR_KIDS", "ALTERED_CONTENT", "RECORDING_DATE", "COVER", "SUBTITLES")
_VISIBILITIES = ("public", "unlisted", "private")
_YES = ("yes", "true", "1")
_NO = ("no", "false", "0")


def _yes_no(header: str, value: str) -> bool | None:
    """True / False for a yes-no setting; None (reported) when it is neither."""
    answer = value.lower()
    if answer in _YES + _NO:
        return answer in _YES
    print(f"youtube.txt {header} {value!r} is not yes/no; ignored.", flush=True)
    return None


def _existing_path(header: str, value: str, base_dir: Path | None) -> Path | None:
    """A path setting resolved against `base_dir`; None (reported) when the file
    does not exist, so a stale youtube.txt never points the upload at nothing."""
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    if path.exists():
        return path
    print(f"youtube.txt {header} {value!r} not found at {path}; ignored.", flush=True)
    return None


def parse_upload_fields(caption: str, base_dir: Path | None = None) -> dict:
    """Upload settings from the setting blocks of a youtube.txt (SETTING_HEADERS),
    as the keys video, playlist, language, category, license, visibility,
    made_for_kids, altered_content, recording_date, cover and subtitles. Paths are
    resolved against `base_dir`, yes/no become bools, the date a datetime.date. A
    missing block is absent from the result; an invalid value is reported and left
    out, so the caller falls back to its own default."""
    values = {}
    section = None
    for line in caption.splitlines():
        header = line.strip().upper()
        if header in TEXT_HEADERS + SETTING_HEADERS:
            section = header
        elif section in SETTING_HEADERS and line.strip() and section not in values:
            values[section] = line.strip()

    fields = {}
    for header, key in (("PLAYLIST", "playlist"), ("LANGUAGE", "language"),
                        ("CATEGORY", "category")):
        if header in values:
            fields[key] = values[header]
    for header, key in (("VIDEO", "video"), ("COVER", "cover"), ("SUBTITLES", "subtitles")):
        if header in values:
            path = _existing_path(header, values[header], base_dir)
            if path is not None:
                fields[key] = path
    for header, key in (("MADE_FOR_KIDS", "made_for_kids"), ("ALTERED_CONTENT", "altered_content")):
        if header in values:
            answer = _yes_no(header, values[header])
            if answer is not None:
                fields[key] = answer
    if "RECORDING_DATE" in values:
        try:
            fields["recording_date"] = date.fromisoformat(values["RECORDING_DATE"])
        except ValueError:
            print(f"youtube.txt RECORDING_DATE {values['RECORDING_DATE']!r} is not "
                  "YYYY-MM-DD; ignored.", flush=True)
    if "LICENSE" in values:
        key = values["LICENSE"].lower()
        if key.startswith("creative"):
            fields["license"] = "creative_commons"
        elif key.startswith("standard"):
            fields["license"] = "standard"
        else:
            print(f"youtube.txt LICENSE {values['LICENSE']!r} is neither creative_commons "
                  "nor standard; ignored.", flush=True)
    if "VISIBILITY" in values:
        if values["VISIBILITY"].lower() in _VISIBILITIES:
            fields["visibility"] = values["VISIBILITY"].lower()
        else:
            print(f"youtube.txt VISIBILITY {values['VISIBILITY']!r} is not one of "
                  f"{', '.join(_VISIBILITIES)}; ignored.", flush=True)
    return fields


def parse_video_id(ref: str) -> str | None:
    """The video id in a bare id, a youtu.be / watch?v= / shorts/ link, or a Studio
    /video/<id>/ URL. Returns None when `ref` holds no id."""
    ref = (ref or "").strip()
    for pattern in _ID_IN_LINK:
        match = re.search(pattern, ref)
        if match:
            return match.group(1)
    return ref if re.fullmatch(_ID, ref) else None


def served_by_oembed(video_url: str, tries: int = 6, wait_s: float = 10.0) -> bool:
    """True once YouTube's oEmbed endpoint returns a title for `video_url`, which
    happens only after a public or unlisted video is published. It is asked `tries`
    times, `wait_s` seconds apart, because the answer can lag the Publish click.
    Returns False for a draft, a private video, or when YouTube cannot be reached."""
    query = urllib.parse.quote(video_url, safe="")
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(OEMBED_URL + query, timeout=15) as reply:
                body = json.loads(reply.read().decode("utf-8"))
            if body.get("title"):
                return True
        except (urllib.error.URLError, ValueError, OSError):
            pass
        if attempt < tries - 1:
            time.sleep(wait_s)
    return False


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
    _DIALOG_FILE_INPUT = "ytcp-uploads-dialog input[type=file]"
    # the picker's visible button; the hidden file input exists before the dialog
    # listens to it, so this button is what shows the dialog is ready for a file
    _SELECT_FILES_BTN = "ytcp-uploads-file-picker #select-files-button, #select-files-button"
    _TITLE_BOX = "#title-textarea #textbox, ytcp-social-suggestions-textbox#title-textarea #textbox"
    _DESC_BOX = "#description-textarea #textbox, ytcp-social-suggestions-textbox#description-textarea #textbox"
    _THUMB_INPUT = "input#file-loader, input[type=file][accept*='image']"
    _NEXT_BTN = "ytcp-button#next-button, #next-button"
    _DONE_BTN = "ytcp-button#done-button, #done-button"
    _MFK_NO = "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']"
    _MFK_YES = "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_MFK']"
    _ALTERED_NO = "tp-yt-paper-radio-button[name='VIDEO_HAS_ALTERED_CONTENT_NO']"
    _ALTERED_YES = "tp-yt-paper-radio-button[name='VIDEO_HAS_ALTERED_CONTENT_YES']"
    # the Category dropdown under Show more shows only its current value, so it is
    # found by its form id rather than by a label
    _CATEGORY_TRIGGER = "ytcp-uploads-dialog ytcp-form-select#category ytcp-text-dropdown-trigger"
    # subtitles on the Video elements step (enabled only once the video language is set)
    _SUBTITLES_BTN = "ytcp-uploads-dialog ytcp-button#subtitles-button"
    _CAPTIONS_MODAL = "ytve-captions-editor-modal"
    _CAPTIONS_UPLOAD_CHOICE = "button#choose-upload-file"
    _CAPTIONS_UPLOAD_DIALOG = "ytve-captions-editor-upload-dialog"
    _CAPTIONS_WITH_TIMING = "tp-yt-paper-radio-button[name=with-timing]"
    _CAPTIONS_CONTINUE = "ytcp-button#confirm-button"
    _CAPTIONS_DONE = "ytcp-button#publish-button"
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
    _VIDEO_LINK = "ytcp-uploads-dialog a#video-link, a#video-link"
    # the Details step's playlist picker (Studio keeps hidden bulk-edit copies of the
    # trigger outside the dialog, so the trigger is scoped to the upload dialog)
    _PLAYLIST_TRIGGER = "ytcp-uploads-dialog ytcp-video-metadata-playlists ytcp-text-dropdown-trigger"
    _PLAYLIST_DIALOG = "ytcp-playlist-dialog"
    _PLAYLIST_SEARCH = "input#search-input"
    _PLAYLIST_ITEM = "label.ytcp-checkbox-label"
    _PLAYLIST_DONE = "ytcp-button.done-button"
    # deleting from the video's edit page: Options menu -> Delete -> confirmation dialog
    _OPTIONS_BTN = "ytcp-icon-button#overflow-menu-button"
    _DELETE_ITEM = "tp-yt-paper-item[test-id=VIDEO_DELETE]"
    _DELETE_DIALOG = "ytcp-confirmation-dialog#delete-dialog"
    _DELETE_CHECKBOX = "ytcp-checkbox-lit#confirm-checkbox"   # click the host: its inner
    _DELETE_CHECK_STATE = "#confirm-checkbox #checkbox"       # box is covered by a container
    _DELETE_CONFIRM = "ytcp-button#confirm-button"
    _DELETE_CANCEL = "ytcp-button#cancel-button"

    #: youtu.be link of the last upload, read from the dialog (None until known)
    video_url: str | None = None

    #: ways to hand Studio the file, tried in this order (see _select_video)
    _SELECT_STRATEGIES = ("set the file", "reload and set the file", "use the file chooser")
    #: seconds the "Select files" button may stay up after the file is handed over
    #: before that attempt counts as not taken
    _NOT_TAKEN_AFTER_S = 45
    #: seconds the Details form may still take once Studio has taken the file
    _DETAILS_AFTER_TAKEN_S = 180

    # Only TRUE post-publish confirmations — NOT "processing"/"uploading" text, which
    # shows during the normal upload and would falsely report success before Publish.
    _SUCCESS_TEXTS = [
        "Video published", "Short published", "is now live", "published to your channel",
        # a long video published before its SD version is ready gets a "Video
        # processing" dialog instead; this sentence appears only after Publish
        "before your video is public",
    ]

    # YouTube's wizard handles cover/audience/visibility itself, so override order.
    def _run_steps(self, page, video: Path, caption: str, cover: Path | None) -> bool:
        self._navigate(page)
        self._select_video(page, video)
        self.video_url = self._read_video_link(page)     # known before Publish, even for a draft
        tags = []
        if caption:
            self._set_caption(page, caption)            # title + description
            tags = self._parse_caption(caption)[2]
        # custom thumbnail: the web app only accepts it for LANDSCAPE, not Shorts
        if cover and not self.is_portrait(video):
            self._set_cover(page, cover)
        elif cover:
            print("Portrait video — custom thumbnail not supported on the web; skipping.", flush=True)
        if self.settings.yt_playlist:
            self._set_playlist(page, self.settings.yt_playlist)
        self._set_made_for_kids(page)
        self._expand_show_more(page)                            # reveals altered-content + tags/lang/date/license
        self._set_altered_content(page)                         # AI/altered-content disclosure -> No
        language = self.settings.yt_language or self._lang_for(video)
        self._set_advanced(page, tags, language)                # tags, language, recording date, license
        self._set_category(page)
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
        """Hand the video to Studio's upload dialog and wait for the Details form.

        Studio can drop the file without a word. On a freshly launched Chrome the
        dialog's hidden file input is in the page before the dialog listens to it,
        so the file is set and nothing happens. Each attempt therefore waits for the
        visible "Select files" button first, then reads the outcome. While that
        button is still on screen Studio has not taken the file and another attempt
        is safe. Once it is gone Studio has started an upload, and another attempt
        would make a second draft, so the run only waits longer. The attempts are
        `_SELECT_STRATEGIES`: set the file, reload the page and set it again, then
        click "Select files" and answer the file chooser as a person would.

        Raises UploadFailed before any other field is touched when no attempt is
        taken, or when Studio took the file but the form never came up. Returns
        None once the Details form is on screen."""
        for attempt, how in enumerate(self._SELECT_STRATEGIES, 1):
            if how.startswith("reload"):
                self._navigate(page)
            if not self._open_picker(page):
                print(f"Upload dialog not ready (attempt {attempt}, {how}).", flush=True)
                continue
            try:
                self._hand_over(page, video, how)
            except Exception as e:
                print(f"Could not hand the file over ({how}): {e}", flush=True)
                continue
            print(f"Video selected ({how}), uploading/processing...", flush=True)
            outcome = self._wait_for_details(page)
            if outcome == "details":
                return
            if outcome == "taken":
                raise UploadFailed(
                    f"Studio took '{video.name}' but the Details form did not appear "
                    f"within {self._DETAILS_AFTER_TAKEN_S} s. A draft may now exist in "
                    "Studio; check Content before uploading again.")
            print(f"Studio did not take the file ({how}); trying another way.", flush=True)
        raise UploadFailed(
            f"Studio never took '{video.name}' after {len(self._SELECT_STRATEGIES)} "
            f"attempts ({', '.join(self._SELECT_STRATEGIES)}). Nothing was uploaded, "
            "so it is safe to run again.")

    def _open_picker(self, page) -> bool:
        """True once the upload dialog shows its "Select files" button. The upload
        URL usually opens the dialog itself; when it does not, the dialog is opened
        the long way, Create -> "Upload videos". False when the button never shows."""
        button = page.locator(self._SELECT_FILES_BTN).first
        try:
            button.wait_for(state="visible", timeout=20000)
        except Exception:
            print("Upload dialog not auto-open; opening via Create -> Upload videos.", flush=True)
            if self._click_first(page, self._CREATE_BTN, timeout=20000):
                page.wait_for_timeout(1000)
                self._click_text(page, self._UPLOAD_ITEM)
            try:
                button.wait_for(state="visible", timeout=30000)
            except Exception:
                return False
        page.wait_for_timeout(1500)   # let the dialog finish wiring its listeners
        return True

    def _hand_over(self, page, video: Path, how: str):
        """Give Studio the file in the way `how` names: answer the file chooser
        that "Select files" opens, or set the dialog's own file input directly
        (any file input when the dialog's own is not found)."""
        if how == "use the file chooser":
            with page.expect_file_chooser(timeout=15000) as chooser:
                page.locator(self._SELECT_FILES_BTN).first.click(timeout=10000)
            chooser.value.set_files(str(video))
            return
        inputs = page.locator(self._DIALOG_FILE_INPUT)
        if not inputs.count():
            inputs = page.locator(self._FILE_INPUT)
        inputs.first.set_input_files(str(video))

    def _wait_for_details(self, page) -> str:
        """Watch the dialog after the file is handed over. Returns "details" once the
        title box is on screen, "not-taken" when the "Select files" button is still
        up after `_NOT_TAKEN_AFTER_S` seconds, or "taken" when that button has gone
        (Studio is uploading) but the title box is still missing after
        `_DETAILS_AFTER_TAKEN_S` more seconds."""
        not_taken_at = time.time() + self._NOT_TAKEN_AFTER_S
        give_up_at = None
        while True:
            if self._visible(page, self._TITLE_BOX):
                return "details"
            now = time.time()
            if self._visible(page, self._SELECT_FILES_BTN):
                if now >= not_taken_at:
                    return "not-taken"
            else:
                if give_up_at is None:
                    give_up_at = now + self._DETAILS_AFTER_TAKEN_S
                if now >= give_up_at:
                    return "taken"
            page.wait_for_timeout(1000)

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
                inp.first.set_input_files(str(self._thumbnail_file(cover)))
                print("Thumbnail uploaded.", flush=True)
                page.wait_for_timeout(3000)
            else:
                print("Thumbnail input not found; skipping.", flush=True)
        except Exception as e:
            print(f"Thumbnail step skipped ({e}).", flush=True)

    @staticmethod
    def _thumbnail_file(cover: Path) -> Path:
        """`cover` itself when it fits YouTube's 2 MB thumbnail limit; otherwise a
        1280-wide JPEG re-encode of it in a temp dir, stepping the quality down
        until it fits. Returns the file to hand to the thumbnail input."""
        cover = Path(cover)
        if cover.stat().st_size <= THUMBNAIL_MAX_BYTES:
            return cover
        target = Path(tempfile.mkdtemp(prefix="yt_thumb_")) / f"{cover.stem}.jpg"
        for quality in (2, 4, 6, 10):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(cover),
                            "-vf", "scale=1280:-2", "-q:v", str(quality), str(target)],
                           check=True)
            if target.stat().st_size <= THUMBNAIL_MAX_BYTES:
                break
        print(f"Cover is over 2 MB; re-encoded to {target} "
              f"({target.stat().st_size // 1024} KiB).", flush=True)
        return target

    def _read_video_link(self, page, timeout_ms: int = 60000) -> str | None:
        """The youtu.be link the upload dialog shows once the file is picked; the id
        exists before Publish, even for a draft. Printed, and returned for the
        ledger. None when it never appears."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                link = page.locator(self._VIDEO_LINK).first
                href = link.get_attribute("href") if link.count() else None
                if href and parse_video_id(href):
                    print(f"Video link: {href}", flush=True)
                    return href
            except Exception:
                pass
            page.wait_for_timeout(1000)
        print("Video link never appeared in the dialog; it is not recorded.", flush=True)
        return None

    def record_extra(self) -> dict:
        """The video id and youtu.be link read from the dialog, plus the playlist, so
        the ledger can later say which video a file became (delete_youtube.py)."""
        return {"video_id": parse_video_id(self.video_url or ""),
                "url": self.video_url, "playlist": self.settings.yt_playlist}

    def _set_playlist(self, page, name: str) -> bool:
        """Tick the playlist titled exactly `name` in the Details step's playlist
        picker, then press Done. Studio's picker search returns nothing for a query
        with brackets, so it searches the plain-word start of the title and then
        matches the full title exactly. Returns True once the trigger shows it."""
        try:
            trigger = page.locator(self._PLAYLIST_TRIGGER).first
            trigger.scroll_into_view_if_needed(timeout=5000)
            trigger.click(timeout=10000)
            dialog = page.locator(self._PLAYLIST_DIALOG).first
            # The dialog's host element has zero height even while open, so Playwright
            # always calls it hidden; wait on its Done button instead.
            dialog.locator(self._PLAYLIST_DONE).first.wait_for(state="visible", timeout=10000)
            query = self._playlist_query(name)
            if query:
                dialog.locator(self._PLAYLIST_SEARCH).first.fill(query)
                page.wait_for_timeout(2000)            # the list filters asynchronously
            exact = re.compile(rf"^\s*{re.escape(name)}\s*$")
            item = dialog.locator(f"{self._PLAYLIST_ITEM}:visible").filter(has_text=exact)
            if not item.count():
                print(f"Playlist '{name}' not found on the channel; add it by hand.", flush=True)
                dialog.locator(self._PLAYLIST_DONE).first.click(timeout=5000)
                return False
            if item.first.locator("#checkbox").get_attribute("aria-checked") != "true":
                item.first.click(timeout=5000)
                page.wait_for_timeout(600)
            dialog.locator(self._PLAYLIST_DONE).first.click(timeout=5000)
            page.wait_for_timeout(1500)
            shown = (trigger.inner_text() or "").strip()
            if name in shown:
                print(f"Playlist set: {name}.", flush=True)
                return True
            print(f"Playlist not confirmed (picker shows {shown!r}); check it by hand.", flush=True)
            return False
        except Exception as e:
            print(f"Playlist step skipped ({e}); add it by hand.", flush=True)
            self._close_overlay(page)
            return False

    @staticmethod
    def _playlist_query(name: str) -> str:
        """The leading run of plain words in a playlist title, used as the picker's
        search query: 'Arsitektur Perangkat Lunak (Sofware Architecture)' gives
        'Arsitektur Perangkat Lunak'. Empty when the title starts with a symbol."""
        return re.match(r"[\w\s&'.,-]*", name).group(0).strip()

    # --- delete -------------------------------------------------------------

    def delete(self, video_id: str, confirm: bool = False) -> bool:
        """Delete one video through its Studio edit page. With confirm=False it only
        opens the delete dialog, prints what the dialog names, and cancels (a dry
        run). Returns True when the video is gone; its ledger record, if any, is then
        removed so the file can be uploaded again without --force."""
        if not self.settings.cdp_url and not (self.settings.profiles_dir / self.site).exists():
            raise LoginRequired(f"No saved profile. Run:  ./venv/bin/python login.py {self.site}")
        with StealthBrowser(self.site, self.settings.profiles_dir,
                            cdp_url=self.settings.cdp_url) as browser:
            page = browser.new_page()
            deleted = self._delete_steps(page, video_id, confirm)
            if browser.attached:
                page.close()          # attach mode opened this tab; leave none behind
        if deleted:
            found = self.ledger.find_record(self.site, video_id=video_id)
            if found:
                self.ledger.forget(self.site, found[0])
                print(f"Removed from the ledger: {found[1].get('name')}", flush=True)
        return deleted

    def _delete_steps(self, page, video_id: str, confirm: bool) -> bool:
        """Edit page -> Options -> Delete -> tick 'I understand' -> confirm, then
        reload the edit page to check the video is really gone."""
        edit_url = f"https://studio.youtube.com/video/{video_id}/edit"
        page.goto(edit_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)                       # Studio is slow to hydrate
        if not self._click_first(page, self._OPTIONS_BTN, timeout=20000):
            print(f"No Options menu for {video_id}: wrong account/channel, or already deleted.",
                  flush=True)
            return False
        page.wait_for_timeout(800)
        if not self._click_first(page, self._DELETE_ITEM, timeout=8000):
            print("'Delete' is missing from the Options menu; delete it by hand.", flush=True)
            self._close_overlay(page)
            return False
        # The dialog's host element has zero height even while open, so Playwright
        # always calls it hidden; its buttons show whether it is really open.
        dialog = page.locator(self._DELETE_DIALOG).first
        cancel = dialog.locator(self._DELETE_CANCEL).first
        cancel.wait_for(state="visible", timeout=15000)
        print(f"Delete dialog: {' '.join((dialog.inner_text() or '').split())[:200]}", flush=True)
        if not confirm:
            cancel.click(timeout=5000)
            print("Dry run: cancelled. Re-run with --yes to delete.", flush=True)
            return False
        dialog.locator(self._DELETE_CHECKBOX).first.click(timeout=5000)
        page.wait_for_timeout(500)
        if dialog.locator(self._DELETE_CHECK_STATE).first.get_attribute("aria-checked") != "true":
            print("Could not tick 'I understand ...'; delete it by hand.", flush=True)
            cancel.click(timeout=5000)
            return False
        button = dialog.locator(self._DELETE_CONFIRM).first
        deadline = time.time() + 10                       # enabled once the box is ticked
        while button.get_attribute("aria-disabled") == "true" and time.time() < deadline:
            page.wait_for_timeout(300)
        button.click(timeout=5000)
        try:
            button.wait_for(state="hidden", timeout=30000)
        except Exception:
            print("The delete dialog did not close; check Studio by hand.", flush=True)
            return False
        page.wait_for_timeout(3000)
        return self._is_gone(page, edit_url)

    def _is_gone(self, page, edit_url: str) -> bool:
        """Reload the edit page and wait for one of two signals: Studio's 'Oops,
        something went wrong' page (the video is gone) or the Options menu (it is
        not). Seeing neither within 30 s counts as not deleted, with a note to check."""
        page.goto(edit_url, wait_until="domcontentloaded", timeout=45000)
        deadline = time.time() + 30
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if page.locator(self._OPTIONS_BTN).count():
                print("The video still opens in Studio; it was NOT deleted.", flush=True)
                return False
            if page.get_by_text("something went wrong", exact=False).count():
                print("Deleted: Studio no longer finds the video.", flush=True)
                return True
        print("Could not confirm the deletion; check Studio by hand.", flush=True)
        return False

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
        """REQUIRED: the 'altered / AI content' disclosure (else Next blocks): Yes
        when settings.yt_altered_content, otherwise No. The section lazy-renders, so
        wait for the radio to appear."""
        selector = self._ALTERED_YES if self.settings.yt_altered_content else self._ALTERED_NO
        answer = "Yes" if self.settings.yt_altered_content else "No"
        # Lives below 'Show more' (expanded just before this) — wait for it to render.
        try:
            page.wait_for_selector(selector, state="attached", timeout=10000)
        except Exception:
            print("Altered-content radio not found (Show more not expanded?); skipping.", flush=True)
            return
        try:
            r = page.locator(selector).first
            r.scroll_into_view_if_needed(timeout=5000)
            r.click(timeout=10000)
            print(f"Altered content (AI use): {answer}.", flush=True)
        except Exception as e:
            print(f"Altered-content click failed ({e}); set it by hand.", flush=True)

    def _set_category(self, page) -> bool:
        """Pick settings.yt_category (e.g. 'Education') in the Category dropdown under
        Show more; nothing to do when it is unset. Returns True once the dropdown
        shows that category."""
        name = self.settings.yt_category
        if not name:
            return False
        try:
            trigger = page.locator(self._CATEGORY_TRIGGER).first
            trigger.scroll_into_view_if_needed(timeout=5000)
            trigger.click(timeout=8000)
            page.wait_for_timeout(1200)
            exact = re.compile(rf"^\s*{re.escape(name)}\s*$")
            option = page.locator("tp-yt-paper-item:visible").filter(has_text=exact)
            if not option.count():
                print(f"Category '{name}' is not offered; set it by hand.", flush=True)
                self._close_overlay(page)
                return False
            option.first.click(timeout=5000)
            page.wait_for_timeout(600)
            if name in (trigger.inner_text() or ""):
                print(f"Category set: {name}.", flush=True)
                return True
            print(f"Category not confirmed; check it by hand.", flush=True)
            return False
        except Exception as e:
            print(f"Category step skipped ({e}); set it by hand.", flush=True)
            self._close_overlay(page)
            return False

    def _set_subtitles(self, page, srt: Path) -> bool:
        """On the Video elements step: Subtitles -> Add -> Upload file -> With timing
        -> Continue -> pick `srt` -> Done. Studio enables Add only once the video
        language is set, so without one this reports and skips. Returns True when
        the subtitle editor accepted the file and closed."""
        try:
            add = page.locator(self._SUBTITLES_BTN).first
            add.wait_for(state="visible", timeout=15000)
            if add.get_attribute("aria-disabled") == "true":
                print("Subtitles need the video language set first; skipping.", flush=True)
                return False
            add.click(timeout=8000)
            modal = page.locator(self._CAPTIONS_MODAL).first
            choice = modal.locator(self._CAPTIONS_UPLOAD_CHOICE).first
            choice.wait_for(state="visible", timeout=15000)
            choice.click(timeout=8000)
            dialog = page.locator(self._CAPTIONS_UPLOAD_DIALOG).first
            timing = dialog.locator(self._CAPTIONS_WITH_TIMING).first
            timing.wait_for(state="visible", timeout=10000)
            timing.click(timeout=5000)
            with page.expect_file_chooser(timeout=15000) as chooser:
                dialog.locator(self._CAPTIONS_CONTINUE).first.click(timeout=8000)
            chooser.value.set_files(str(srt))
            done = modal.locator(self._CAPTIONS_DONE).first
            deadline = time.time() + 60                   # enabled once the file is parsed
            while done.get_attribute("aria-disabled") == "true" and time.time() < deadline:
                page.wait_for_timeout(500)
            done.click(timeout=8000)
            done.wait_for(state="hidden", timeout=30000)
            print(f"Subtitles uploaded: {Path(srt).name}.", flush=True)
            return True
        except Exception as e:
            print(f"Subtitles step skipped ({e}); add them by hand.", flush=True)
            return False

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
            self._close_overlay(page)
        except Exception as e:
            print(f"Related-video step skipped ({e}).", flush=True)
            try:
                self._close_overlay(page)
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
            # Dismiss the tag-suggestion overlay by moving focus, NOT with Escape:
            # inside a modal, Escape tells the whole upload dialog to CLOSE — the
            # dialog then tears down/re-renders, its `dialog-scrim` covers everything,
            # and every later step ("intercepts pointer events" / "element was
            # detached from the DOM") fails. Tab just leaves the field.
            box.first.press("Tab")
            page.wait_for_timeout(800)
            print(f"Tags set ({len(tags)}).", flush=True)
        except Exception as e:
            print(f"Tags step skipped ({e}).", flush=True)

    @staticmethod
    def _close_overlay(page):
        """Close an open dropdown menu / picker with Escape — but ONLY if one is
        actually open. A stray Escape inside the modal tells the whole upload dialog
        to close, which tears it down and breaks every step after it."""
        try:
            open_overlay = page.evaluate(
                """() => { const vis = e => e && e.offsetParent !== null;
                     return [...document.querySelectorAll(
                       'tp-yt-iron-dropdown, tp-yt-paper-dialog, ytcp-video-pick-dialog, '
                       + 'tp-yt-iron-overlay-backdrop')].some(vis); }"""
            )
            if open_overlay:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
        except Exception:
            pass

    @staticmethod
    def _scope(page):
        """Search INSIDE the upload dialog when it's open. Studio keeps a second copy
        of these controls on the page behind the dialog; picking that one means the
        click is swallowed by the dialog's `dialog-scrim` overlay ("intercepts pointer
        events") and every later step fails."""
        try:
            dlg = page.locator("ytcp-uploads-dialog")
            if dlg.count() and dlg.first.is_visible():
                return dlg.first
        except Exception:
            pass
        return page

    def _dropdown_trigger(self, page, label: str):
        """The visible dropdown trigger for `label`, scoped to the upload dialog."""
        trig = self._scope(page).locator(self._DROPDOWN).filter(has_text=label)
        for i in range(trig.count()):
            try:
                if trig.nth(i).is_visible():
                    return trig.nth(i)
            except Exception:
                continue
        return None

    def _select_dropdown(self, page, label: str, option: str, exact_option: bool = True) -> bool:
        """Open the Studio dropdown whose trigger contains `label`, click `option`."""
        try:
            trig = self._dropdown_trigger(page, label)
            if trig is None:
                return False
            trig.scroll_into_view_if_needed(timeout=5000)
            trig.click(timeout=8000)
            page.wait_for_timeout(1200)            # let the option menu render
            opt = page.get_by_text(option, exact=exact_option)
            if not opt.count():
                opt = page.locator(self._MENU_ITEM).filter(has_text=option)
            if opt.count() and opt.first.is_visible():
                opt.first.click()
                page.wait_for_timeout(500)
                return True
            self._close_overlay(page)
            return False
        except Exception:
            try:
                self._close_overlay(page)
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
            trig = self._dropdown_trigger(page, "Video language")
            if trig is None:
                print("Language dropdown not found; set it by hand.", flush=True); return
            for _ in range(4):
                ab = page.get_by_text("Abkhazian", exact=True)
                if ab.count() and ab.first.is_visible():
                    break                                 # menu genuinely OPEN (items keep
                trig.scroll_into_view_if_needed(timeout=5000)         # living in the DOM when
                trig.click(timeout=8000)                              # closed, so count() lies)
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
                self._close_overlay(page)
        except Exception as e:
            print(f"Language step skipped ({e}); set it by hand.", flush=True)
            try:
                self._close_overlay(page)
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
        """Recording date = settings.yt_recording_date, else today."""
        try:
            today = self.settings.yt_recording_date or date.today()
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
                self._close_overlay(page)
        except Exception as e:
            print(f"Recording-date step skipped ({e}).", flush=True)

    def _enable_ai_disclosure(self, page):
        # Abstract base requires it; the YouTube wizard (above) doesn't use it.
        pass

    def _post(self, page) -> bool:
        # Details -> Video elements -> Checks -> Visibility (3 x Next)
        for step in range(3):
            if not self._click_first(page, self._NEXT_BTN, timeout=15000):
                break
            page.wait_for_timeout(1500)
            if step == 0 and self.settings.yt_subtitles:      # now on Video elements
                self._set_subtitles(page, self.settings.yt_subtitles)
        self._set_visibility(page)

        if not self.settings.auto_post:
            chosen = (self.settings.yt_visibility or "public").lower()
            print(f"\nReady on the Visibility step ({chosen} selected) — saved as a draft. "
                  "Review and Publish by hand when you like (--no-post records nothing).", flush=True)
            return False

        # Publishing while checks are still running pops a strike-risk warning;
        # wait for "Checks complete" first to avoid it.
        self._wait_for_checks(page, 120000)
        if self._click_publish(page):
            print("Clicked Publish; waiting for confirmation...", flush=True)
        else:
            print("Publish button never became clickable; click it by hand.", flush=True)
        posted = self._wait_for_success(page, 120000, confirm=True)
        # Studio rewords its post-Publish dialogs now and then, so a published video
        # can go unnoticed. A public or unlisted one can still be confirmed from
        # outside Studio; a private one cannot, and stays unconfirmed.
        visibility = (self.settings.yt_visibility or "public").lower()
        if not posted and self.video_url and visibility != "private":
            print("No publish confirmation on screen; asking YouTube whether it serves "
                  f"{self.video_url} ...", flush=True)
            posted = served_by_oembed(self.video_url)
            if posted:
                print("YouTube serves the video (oEmbed); counting it as published.",
                      flush=True)
        return posted

    def retry_note(self) -> str:
        """Say "safe to retry" only while Studio holds no video from this run. Once
        the dialog showed a link Studio has a video, draft or published, so running
        again would upload a second copy."""
        if self.video_url:
            return (f"but Studio already holds {self.video_url}; check it there before "
                    "running again, or a second copy is uploaded")
        return "safe to retry"

    def _click_publish(self, page, timeout_ms: int = 90000) -> bool:
        """Click Publish, retrying until it works. The button is often present but
        still DISABLED (upload/checks finishing), so a single click attempt silently
        failed and left the video as a draft — the main intermittent failure."""
        deadline = time.time() + timeout_ms / 1000
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                btn = page.locator(self._DONE_BTN).first
                if btn.count() and btn.is_visible() \
                        and btn.get_attribute("aria-disabled") != "true":
                    btn.click(timeout=8000)
                    return True
                # fall back to the button's text (Publish / Save / Done)
                for name in ("Publish", "Save", "Done"):
                    b = page.get_by_role("button", name=name, exact=True)
                    if b.count() and b.first.is_visible() \
                            and b.first.get_attribute("aria-disabled") != "true":
                        b.first.click(timeout=8000)
                        return True
            except Exception as e:
                if attempt == 1:
                    print(f"Publish click retrying ({e})...", flush=True)
            page.wait_for_timeout(3000)
        return False

    def _confirm_publish_dialog(self, page) -> bool:
        """Click through the post-Publish dialogs YouTube may raise (the
        'still checking your content' strike warning, etc.)."""
        for name in ("Publish anyway", "Publish", "Continue", "Got it"):
            try:
                b = page.get_by_role("button", name=name, exact=True)
                if b.count() and b.first.is_visible():
                    b.first.click(timeout=5000)
                    print(f"Confirmed dialog: '{name}'.", flush=True)
                    return True
            except Exception:
                pass
        return False

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
        """Parse the caption text into (title<=100, description, [tags]).

        Two supported layouts:

        1. Marker-based (explicit section headers on their own lines)::

               TITLE
               <the title>
               DESCRIPTION
               <body + #hashtags>
               KEYWORDS
               <comma, separated, list>

        2. Positional (no markers) — the simpler, preferred format::

               <title — everything before the FIRST blank line>

               <description — everything between>

               <keywords — everything after the LAST blank line, comma-separated>

        The marker-based path is tried first; positional is used when none of
        the markers are found in the text. The upload-setting blocks a
        slides_narrator youtube.txt adds after KEYWORDS (PLAYLIST, LANGUAGE, ...)
        are markers too, so their values never leak into the tags; they are read
        by parse_upload_fields.
        """
        buckets = {header: [] for header in TEXT_HEADERS + SETTING_HEADERS}
        section = None
        has_markers = False
        for ln in caption.splitlines():
            key = ln.strip().upper()
            if key in buckets:
                section = key
                has_markers = True
                continue
            if section:
                buckets[section].append(ln)

        if has_markers:
            # --- marker-based path ---
            title = " ".join(l.strip() for l in buckets["TITLE"] if l.strip())[:100]
            desc = "\n".join(buckets["DESCRIPTION"]).strip()
            kw = " ".join(l.strip() for l in buckets["KEYWORDS"] if l.strip())
            tags = [t.strip() for t in kw.split(",") if t.strip()]
            if not title:
                title = "Untitled"
            return title, desc, tags

        # --- positional (blank-line) layout ---
        # title = text before the FIRST blank line; keywords = text after the LAST
        # blank line; description = everything in between.
        lines = caption.strip("\n").split("\n")
        blanks = [i for i, l in enumerate(lines) if not l.strip()]
        if not blanks:                                  # no blank line: it's all title
            title = " ".join(l.strip() for l in lines if l.strip())[:100] or "Untitled"
            return title, "", []
        first, last = blanks[0], blanks[-1]
        title = " ".join(l.strip() for l in lines[:first] if l.strip())[:100]
        if last > first:                                # title | description | keywords
            desc = "\n".join(lines[first + 1:last]).strip()
            kw = "\n".join(lines[last + 1:]).strip()
        else:                                           # only one blank line: title | description
            desc = "\n".join(lines[first + 1:]).strip()
            kw = ""
        tags = [t.strip() for t in kw.replace("\n", ",").split(",") if t.strip()]
        if not title:
            title = (next((l.strip() for l in lines if l.strip()), "")[:100]) or "Untitled"
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
            # Clear via the ELEMENT: locator.press() focuses it first. A plain
            # page.keyboard select-all can miss Studio's contenteditable, so Delete
            # clears nothing and the new text is APPENDED onto YouTube's pre-filled
            # value — which is what concatenates the title/description.
            box.press("Control+a")
            box.press("Delete")
            page.keyboard.insert_text(text)        # instant on long text, unlike .type()
            page.wait_for_timeout(300)
            got = (box.inner_text() or "").strip()
            if got[:40].strip() != text[:40].strip():
                print(f"{label} MISMATCH — box starts {got[:60]!r} (expected {text[:40]!r})",
                      flush=True)
            else:
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
    def _visible(page, selector_csv: str) -> bool:
        """True when any of the comma-separated selectors has a visible match."""
        for sel in (s.strip() for s in selector_csv.split(",") if s.strip()):
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _click_text(page, text: str) -> bool:
        loc = page.get_by_text(text, exact=False)
        if loc.count() and loc.first.is_visible():
            loc.first.click()
            return True
        return False

    def _wait_for_success(self, page, timeout_ms: int, confirm: bool = False) -> bool:
        """Watch for a publish confirmation. With confirm=True also clicks any
        post-Publish dialog (e.g. the 'still checking your content' warning), which
        can appear seconds later and otherwise blocks the publish from completing."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                for txt in self._SUCCESS_TEXTS:
                    if page.get_by_text(txt, exact=False).count():
                        return True
                if confirm:
                    self._confirm_publish_dialog(page)
            except Exception:
                pass
            page.wait_for_timeout(1500)
        return False
