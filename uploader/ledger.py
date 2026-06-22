"""Tracks which videos have already been posted, so nothing is uploaded twice.

Keyed by the video's SHA-256 content hash -> survives renames/moves.
Stored as JSON. A video is only recorded after a CONFIRMED post.
"""
import json
import hashlib
import time
from pathlib import Path


class Ledger:
    """A JSON-backed record of uploaded videos, keyed by content hash."""

    def __init__(self, path: Path):
        self.path = Path(path)

    # --- public API -------------------------------------------------------

    def video_key(self, path) -> str:
        return self._hash(path)

    def is_uploaded(self, path, platform: str | None = None) -> bool:
        rec = self._load().get(self.video_key(path))
        if not rec:
            return False
        if platform:
            return platform in rec.get("platforms", [])
        return True

    def get_record(self, path) -> dict | None:
        return self._load().get(self.video_key(path))

    def mark_uploaded(self, path, platform: str = "tiktok", caption: str = "") -> dict:
        data = self._load()
        key = self.video_key(path)
        rec = data.get(key, {
            "name": Path(path).name,
            "path": str(Path(path).resolve()),
            "platforms": [],
            "caption_preview": (caption or "").replace("\n", " ")[:80],
            "first_uploaded": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if platform not in rec["platforms"]:
            rec["platforms"].append(platform)
        rec["last_uploaded"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data[key] = rec
        self._save(data)
        return rec

    def list_records(self) -> dict:
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
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
