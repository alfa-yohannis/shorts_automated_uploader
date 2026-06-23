"""Project-wide settings, resolved relative to the repo root."""
from dataclasses import dataclass, field
from pathlib import Path

# uploader/config.py -> repo root is two levels up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Tunable knobs + resolved paths. Construct with defaults, or override
    fields (e.g. ``Settings(auto_post=True)``) for hands-off posting."""

    auto_post: bool = False          # auto-click the Post button when True
    disclose_ai: bool = True         # turn ON the "AI-generated content" toggle (TikTok)
    portrait_glob: str = "*_portrait_*.mp4"   # only files matching this upload

    # YouTube knobs.
    yt_visibility: str = "public"    # public | unlisted | private (Visibility step)
    yt_made_for_kids: bool = False   # the required "made for kids" audience flag
    yt_channel_id: str = "UCEWLCMe8iwKOakYoaQ2k1eg"   # Studio channel to upload to
    yt_license: str = "creative_commons"   # creative_commons | standard

    profiles_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "profiles")
    ledger_path: Path = field(default_factory=lambda: PROJECT_ROOT / "ledger.json")

    # Attach to an already-running Chrome over the DevTools protocol instead of
    # launching our own stealth context. Set this when a site (e.g. Instagram)
    # only stays logged-in inside your real, keyring-backed Chrome profile.
    # e.g. "http://127.0.0.1:9222"
    cdp_url: str | None = None
