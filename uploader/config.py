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
    disclose_ai: bool = True         # turn ON the "AI-generated content" toggle
    portrait_glob: str = "*_portrait_*.mp4"   # only files matching this upload

    profiles_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "profiles")
    ledger_path: Path = field(default_factory=lambda: PROJECT_ROOT / "ledger.json")
