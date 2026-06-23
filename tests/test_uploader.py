"""Unit tests for Settings, the portrait/caption/cover rules, and the upload()
guard logic. Browser-driven steps are not exercised here (covered by live runs /
dev probes); a mocked StealthBrowser checks the orchestration + ledger recording.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from uploader import Settings, Ledger, AlreadyUploaded, UploadSkipped, LoginRequired
from uploader.uploaders.base import VideoUploader


class FakeUploader(VideoUploader):
    """Concrete uploader with no-op page steps, for browser-free testing."""
    site = "tiktok"

    def _navigate(self, page): pass
    def _select_video(self, page, video): pass
    def _set_caption(self, page, caption): pass
    def _enable_ai_disclosure(self, page): pass
    def _set_cover(self, page, cover): pass
    def _post(self, page): return True


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertFalse(s.auto_post)
        self.assertTrue(s.disclose_ai)
        self.assertEqual(s.portrait_glob, "*_portrait_*.mp4")
        self.assertIsNone(s.cdp_url)

    def test_override(self):
        s = Settings(auto_post=True, cdp_url="http://127.0.0.1:9222")
        self.assertTrue(s.auto_post)
        self.assertEqual(s.cdp_url, "http://127.0.0.1:9222")


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.up = FakeUploader(Settings(profiles_dir=self.tmp / "profiles",
                                        ledger_path=self.tmp / "ledger.json"))

    def test_is_portrait(self):
        self.assertTrue(self.up.is_portrait(Path("x_portrait_id.mp4")))
        self.assertTrue(self.up.is_portrait(Path("A_PORTRAIT_EN.MP4")))   # case-insensitive
        self.assertFalse(self.up.is_portrait(Path("clip.mp4")))

    def test_resolve_caption_literal_vs_file(self):
        self.assertEqual(self.up.resolve_caption("just text"), "just text")
        txt = self.tmp / "cap.txt"
        txt.write_text("  from file  \n")
        self.assertEqual(self.up.resolve_caption(str(txt)), "from file")

    def test_resolve_cover(self):
        video = self.tmp / "v_portrait_id.mp4"
        video.write_bytes(b"v")
        self.assertIsNone(self.up.resolve_cover(video, None))     # no sibling
        (self.tmp / "v_portrait_id.png").write_bytes(b"img")
        self.assertEqual(self.up.resolve_cover(video, None).suffix, ".png")
        explicit = self.tmp / "other.jpg"
        explicit.write_bytes(b"i")
        self.assertEqual(self.up.resolve_cover(video, str(explicit)).name, "other.jpg")


class UploadGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = Settings(profiles_dir=self.tmp / "profiles",
                                 ledger_path=self.tmp / "ledger.json")
        self.ledger = Ledger(self.settings.ledger_path)
        self.video = self.tmp / "v_portrait_id.mp4"
        self.video.write_bytes(b"bytes")

    def _uploader(self, **over):
        s = Settings(profiles_dir=self.settings.profiles_dir,
                     ledger_path=self.settings.ledger_path, **over)
        return FakeUploader(s, self.ledger)

    def test_non_portrait_skipped(self):
        bad = self.tmp / "landscape.mp4"
        bad.write_bytes(b"x")
        with self.assertRaises(UploadSkipped):
            self._uploader().upload(bad)

    def test_already_uploaded_raises(self):
        self.ledger.mark_uploaded(self.video, "tiktok")
        with self.assertRaises(AlreadyUploaded):
            self._uploader().upload(self.video)

    def test_already_uploaded_is_an_upload_skipped(self):
        self.ledger.mark_uploaded(self.video, "tiktok")
        # AlreadyUploaded subclasses UploadSkipped, so a broad catch still works
        with self.assertRaises(UploadSkipped):
            self._uploader().upload(self.video)

    def test_force_bypasses_ledger(self):
        self.ledger.mark_uploaded(self.video, "tiktok")
        with mock.patch("uploader.uploaders.base.StealthBrowser"):
            posted = self._uploader(cdp_url="http://x").upload(self.video, force=True)
        self.assertTrue(posted)

    def test_login_required_without_profile_or_cdp(self):
        with self.assertRaises(LoginRequired):
            self._uploader().upload(self.video)   # fresh video, no profile, no cdp

    def test_success_records_ledger(self):
        with mock.patch("uploader.uploaders.base.StealthBrowser"):
            posted = self._uploader(cdp_url="http://x", auto_post=True).upload(self.video, caption="hi")
        self.assertTrue(posted)
        self.assertTrue(self.ledger.is_uploaded(self.video, "tiktok"))
        self.assertFalse(self.ledger.is_uploaded(self.video, "instagram"))

    def test_no_post_does_not_record(self):
        # --no-post (auto_post=False) is a manual/preview run: even a detected
        # share must NOT be recorded, so the video stays re-runnable.
        with mock.patch("uploader.uploaders.base.StealthBrowser"):
            posted = self._uploader(cdp_url="http://x", auto_post=False).upload(self.video, caption="hi")
        self.assertTrue(posted)                                       # it did "post"
        self.assertFalse(self.ledger.is_uploaded(self.video, "tiktok"))   # but not recorded


if __name__ == "__main__":
    unittest.main()
