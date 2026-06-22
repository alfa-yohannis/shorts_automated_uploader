"""Abstract video uploader.

Holds the platform-agnostic orchestration (portrait rule, ledger guard,
browser lifecycle, recording) as a template method. Concrete subclasses
implement the per-platform page interactions.
"""
import fnmatch
from abc import ABC, abstractmethod
from pathlib import Path

from ..browser import StealthBrowser
from ..config import Settings
from ..ledger import Ledger


class UploadSkipped(Exception):
    """Raised when a video is intentionally not uploaded (rule/ledger)."""


class LoginRequired(Exception):
    """Raised when no saved profile exists for the platform."""


class VideoUploader(ABC):
    """Template-method base for all platform uploaders."""

    #: platform key, e.g. "tiktok" — used for the profile dir and ledger.
    site: str = ""
    #: page the upload flow runs on.
    upload_url: str = ""

    def __init__(self, settings: Settings | None = None, ledger: Ledger | None = None):
        self.settings = settings or Settings()
        self.ledger = ledger or Ledger(self.settings.ledger_path)

    # --- public API -------------------------------------------------------

    def is_portrait(self, video: Path) -> bool:
        return fnmatch.fnmatch(video.name.lower(), self.settings.portrait_glob)

    def upload(self, video: Path, caption: str = "", cover: Path | None = None,
               force: bool = False) -> bool:
        """Run the full flow. Returns True if a post was confirmed & recorded.

        Raises UploadSkipped (portrait rule / already uploaded) or
        LoginRequired (no saved profile)."""
        video = Path(video).resolve()

        if not self.is_portrait(video):
            raise UploadSkipped(
                f"'{video.name}' is not a portrait video "
                f"({self.settings.portrait_glob}). Not uploading."
            )

        if self.ledger.is_uploaded(video, platform=self.site) and not force:
            when = (self.ledger.get_record(video) or {}).get("last_uploaded", "?")
            raise UploadSkipped(
                f"'{video.name}' was already uploaded to {self.site} on {when}. "
                "Use --force to upload it again."
            )

        profile = self.settings.profiles_dir / self.site
        if not profile.exists():
            raise LoginRequired(
                f"No saved profile. Run:  ./venv/bin/python login.py {self.site}"
            )

        with StealthBrowser(self.site, self.settings.profiles_dir) as browser:
            page = browser.new_page()
            self._navigate(page)
            self._select_video(page, video)
            if caption:
                self._set_caption(page, caption)
            if self.settings.disclose_ai:
                self._enable_ai_disclosure(page)
            if cover:
                self._set_cover(page, cover)
            posted = self._post(page)

        if posted:
            self.ledger.mark_uploaded(video, platform=self.site, caption=caption)
            print(f"POSTED & recorded in ledger: {video.name}", flush=True)
        else:
            print("No confirmed post detected -> NOT recorded (safe to retry).", flush=True)
        return posted

    # --- input resolution helpers ----------------------------------------

    @staticmethod
    def resolve_caption(arg: str) -> str:
        """A literal caption string, or the contents of a .txt path."""
        if arg.lower().endswith(".txt") and Path(arg).exists():
            return Path(arg).read_text(encoding="utf-8").strip()
        return arg

    @staticmethod
    def resolve_cover(video: Path, explicit: str | None) -> Path | None:
        if explicit:
            cover = Path(explicit)
            return cover if cover.exists() else None
        for ext in (".png", ".jpg", ".jpeg"):   # auto-detect sibling image
            cand = video.with_suffix(ext)
            if cand.exists():
                return cand
        return None

    # --- per-platform steps (subclasses implement) -----------------------

    @abstractmethod
    def _navigate(self, page): ...

    @abstractmethod
    def _select_video(self, page, video: Path): ...

    @abstractmethod
    def _set_caption(self, page, caption: str): ...

    @abstractmethod
    def _enable_ai_disclosure(self, page): ...

    @abstractmethod
    def _set_cover(self, page, cover: Path): ...

    @abstractmethod
    def _post(self, page) -> bool: ...
