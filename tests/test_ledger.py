"""Unit tests for the per-platform Ledger."""
import json
import tempfile
import unittest
from pathlib import Path

from uploader import Ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = Ledger(self.tmp / "ledger.json")
        self.video = self.tmp / "demo_portrait_id.mp4"
        self.video.write_bytes(b"some video bytes")

    def test_empty_when_new(self):
        self.assertEqual(self.ledger.list_records(), {})
        self.assertFalse(self.ledger.is_uploaded(self.video))
        self.assertFalse(self.ledger.is_uploaded(self.video, "tiktok"))

    def test_mark_and_check_per_platform(self):
        self.ledger.mark_uploaded(self.video, "instagram", caption="hi")
        # recorded for instagram only
        self.assertTrue(self.ledger.is_uploaded(self.video, "instagram"))
        self.assertFalse(self.ledger.is_uploaded(self.video, "tiktok"))
        # "any platform" check is True
        self.assertTrue(self.ledger.is_uploaded(self.video))

    def test_two_separate_lists(self):
        self.ledger.mark_uploaded(self.video, "instagram")
        self.ledger.mark_uploaded(self.video, "tiktok")
        data = self.ledger.list_records()
        self.assertEqual(set(data), {"instagram", "tiktok"})
        key = self.ledger.video_key(self.video)
        self.assertIn(key, data["instagram"])
        self.assertIn(key, data["tiktok"])

    def test_record_fields_and_no_platforms_array(self):
        rec = self.ledger.mark_uploaded(self.video, "tiktok", caption="line1\nline2")
        self.assertEqual(rec["name"], "demo_portrait_id.mp4")
        self.assertIn("first_uploaded", rec)
        self.assertIn("last_uploaded", rec)
        self.assertEqual(rec["caption_preview"], "line1 line2")
        self.assertNotIn("platforms", rec)   # new layout drops the array

    def test_hash_keyed_survives_rename(self):
        self.ledger.mark_uploaded(self.video, "tiktok")
        renamed = self.tmp / "totally_different_name.mp4"
        renamed.write_bytes(b"some video bytes")   # same content
        self.assertTrue(self.ledger.is_uploaded(renamed, "tiktok"))

    def test_get_record_scoped(self):
        self.ledger.mark_uploaded(self.video, "instagram")
        self.assertIsNotNone(self.ledger.get_record(self.video, "instagram"))
        self.assertIsNone(self.ledger.get_record(self.video, "tiktok"))
        self.assertIsNotNone(self.ledger.get_record(self.video))   # any

    def test_migrates_old_flat_format(self):
        key = self.ledger.video_key(self.video)
        old = {
            key: {
                "name": "demo_portrait_id.mp4",
                "path": str(self.video),
                "platforms": ["tiktok", "instagram"],
                "caption_preview": "old",
                "first_uploaded": "2026-01-01 00:00:00",
                "last_uploaded": "2026-01-02 00:00:00",
            }
        }
        (self.tmp / "ledger.json").write_text(json.dumps(old), encoding="utf-8")
        data = self.ledger.list_records()
        self.assertEqual(set(data), {"tiktok", "instagram"})
        self.assertIn(key, data["tiktok"])
        self.assertNotIn("platforms", data["tiktok"][key])
        self.assertTrue(self.ledger.is_uploaded(self.video, "tiktok"))


if __name__ == "__main__":
    unittest.main()
