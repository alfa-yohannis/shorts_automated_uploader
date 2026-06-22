"""Tracks which videos have already been posted, so nothing is uploaded twice.

Structure (JSON), keyed by PLATFORM, then by the video's SHA-256 content hash
(which survives renames/moves):

    {
      "tiktok":    { "<sha256>": {name, path, caption_preview, first_uploaded, last_uploaded} },
      "instagram": { "<sha256>": {...} }
    }

A video is only recorded after a CONFIRMED post.
"""
import json
import hashlib
import time
from pathlib import Path

_REC_FIELDS = ("name", "path", "caption_preview", "first_uploaded", "last_uploaded")


class Ledger:
    """A JSON-backed record of uploaded videos, one list per platform."""

    def __init__(self, path: Path):
        self.path = Path(path)

    # --- public API -------------------------------------------------------

    def video_key(self, path) -> str:
        return self._hash(path)

    def is_uploaded(self, path, platform: str | None = None) -> bool:
        data = self._load()
        key = self.video_key(path)
        if platform:
            return key in data.get(platform, {})
        return any(key in vids for vids in data.values())

    def get_record(self, path, platform: str | None = None) -> dict | None:
        data = self._load()
        key = self.video_key(path)
        if platform:
            return data.get(platform, {}).get(key)
        for vids in data.values():          # any platform
            if key in vids:
                return vids[key]
        return None

    def mark_uploaded(self, path, platform: str = "tiktok", caption: str = "") -> dict:
        data = self._load()
        key = self.video_key(path)
        bucket = data.setdefault(platform, {})
        rec = bucket.get(key, {
            "name": Path(path).name,
            "path": str(Path(path).resolve()),
            "caption_preview": (caption or "").replace("\n", " ")[:80],
            "first_uploaded": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        rec["last_uploaded"] = time.strftime("%Y-%m-%d %H:%M:%S")
        bucket[key] = rec
        self._save(data)
        return rec

    def list_records(self) -> dict:
        """Return {platform: {hash: record}}."""
        return self._load()

    # --- internals --------------------------------------------------------

    @staticmethod
    def _hash(path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return self._migrate(raw)

    @staticmethod
    def _migrate(raw: dict) -> dict:
        """Convert the old flat {hash: {..., platforms:[...]}} layout to the
        per-platform {platform: {hash: record}} layout."""
        if not raw:
            return {}
        # old format if any top-level value is a record (has "name")
        if not any(isinstance(v, dict) and "name" in v for v in raw.values()):
            return raw
        migrated: dict = {}
        for key, rec in raw.items():
            slim = {k: rec[k] for k in _REC_FIELDS if k in rec}
            for platform in rec.get("platforms", []):
                migrated.setdefault(platform, {})[key] = dict(slim)
        return migrated

    def _save(self, data: dict):
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
