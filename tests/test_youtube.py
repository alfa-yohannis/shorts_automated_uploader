"""Unit tests for the YouTube additions: video-id parsing, the playlist search query,
the 2 MB thumbnail guard, the slides/ cover fallback, the ledger's video_id fields,
and how delete_youtube.py resolves its target. No browser, no network; the
thumbnail test needs ffmpeg and is skipped without it.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delete_youtube
from uploader import Settings, Ledger, YouTubeUploader
from uploader.uploaders.base import VideoUploader
from uploader.uploaders.youtube import THUMBNAIL_MAX_BYTES, parse_video_id


class FakeUploader(VideoUploader):
    """No-op page steps, plus a record_extra like YouTube's, to test the wiring."""
    site = "youtube"
    enforce_portrait = False

    def _navigate(self, page): pass
    def _select_video(self, page, video): pass
    def _set_caption(self, page, caption): pass
    def _enable_ai_disclosure(self, page): pass
    def _set_cover(self, page, cover): pass
    def _post(self, page): return True

    def record_extra(self):
        return {"video_id": "t9Z0Bku_itE", "url": "https://youtu.be/t9Z0Bku_itE", "playlist": None}


class ParseVideoIdTests(unittest.TestCase):
    def test_link_forms(self):
        for ref in ("https://youtu.be/t9Z0Bku_itE",
                    "https://www.youtube.com/watch?v=t9Z0Bku_itE&t=3",
                    "https://youtube.com/shorts/t9Z0Bku_itE",
                    "https://studio.youtube.com/video/t9Z0Bku_itE/edit",
                    "  t9Z0Bku_itE  "):
            self.assertEqual(parse_video_id(ref), "t9Z0Bku_itE", ref)

    def test_no_id(self):
        for ref in ("", "session10.mp4", "https://youtu.be/", "not an id at all"):
            self.assertIsNone(parse_video_id(ref), ref)


class PlaylistQueryTests(unittest.TestCase):
    def test_stops_before_brackets(self):
        query = YouTubeUploader._playlist_query("Arsitektur Perangkat Lunak (Sofware Architecture)")
        self.assertEqual(query, "Arsitektur Perangkat Lunak")

    def test_plain_titles_are_kept(self):
        self.assertEqual(YouTubeUploader._playlist_query("Enterprise & Platform Architecture"),
                         "Enterprise & Platform Architecture")
        self.assertEqual(YouTubeUploader._playlist_query("Java Shorts"), "Java Shorts")

    def test_symbol_first_gives_empty_query(self):
        self.assertEqual(YouTubeUploader._playlist_query("(Draft) Notes"), "")


class ThumbnailGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_small_cover_is_used_as_is(self):
        cover = self.tmp / "slide_01.png"
        cover.write_bytes(b"x" * 1000)
        self.assertEqual(YouTubeUploader._thumbnail_file(cover), cover)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_large_cover_is_reencoded_under_the_limit(self):
        cover = self.tmp / "noise.png"           # random noise barely compresses
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "nullsrc=s=1600x1600,geq=random(1)*255:random(2)*255:random(3)*255",
                        "-frames:v", "1", str(cover)], check=True)
        self.assertGreater(cover.stat().st_size, THUMBNAIL_MAX_BYTES)
        thumb = YouTubeUploader._thumbnail_file(cover)
        self.assertEqual(thumb.suffix, ".jpg")
        self.assertLessEqual(thumb.stat().st_size, THUMBNAIL_MAX_BYTES)


class SlidesCoverTests(unittest.TestCase):
    def test_first_slide_png_when_no_sibling_image(self):
        tmp = Path(tempfile.mkdtemp())
        video = tmp / "session10.mp4"
        video.write_bytes(b"v")
        self.assertIsNone(VideoUploader.resolve_cover(video, None))
        (tmp / "slides").mkdir()
        for name in ("slide_02.png", "slide_01.png", "slide_10.png"):
            (tmp / "slides" / name).write_bytes(b"img")
        self.assertEqual(VideoUploader.resolve_cover(video, None).name, "slide_01.png")
        (tmp / "session10.png").write_bytes(b"img")          # a sibling image still wins
        self.assertEqual(VideoUploader.resolve_cover(video, None).name, "session10.png")


class LedgerVideoIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = Ledger(self.tmp / "ledger.json")
        self.video = self.tmp / "session10.mp4"
        self.video.write_bytes(b"lecture bytes")

    def test_extra_fields_are_stored_and_found(self):
        self.ledger.mark_uploaded(self.video, "youtube",
                                  extra={"video_id": "t9Z0Bku_itE", "playlist": None})
        rec = self.ledger.get_record(self.video, "youtube")
        self.assertEqual(rec["video_id"], "t9Z0Bku_itE")
        self.assertNotIn("playlist", rec)                      # empty values are skipped
        key, found = self.ledger.find_record("youtube", video_id="t9Z0Bku_itE")
        self.assertEqual(found["name"], "session10.mp4")
        self.assertIsNone(self.ledger.find_record("youtube", video_id="other_id_00"))

    def test_forget_drops_only_that_record(self):
        self.ledger.mark_uploaded(self.video, "youtube", extra={"video_id": "t9Z0Bku_itE"})
        self.ledger.mark_uploaded(self.video, "tiktok")
        key, _ = self.ledger.find_record("youtube", video_id="t9Z0Bku_itE")
        self.assertIsNotNone(self.ledger.forget("youtube", key))
        self.assertFalse(self.ledger.is_uploaded(self.video, "youtube"))
        self.assertTrue(self.ledger.is_uploaded(self.video, "tiktok"))
        self.assertIsNone(self.ledger.forget("youtube", key))  # already gone

    def test_confirmed_upload_records_record_extra(self):
        settings = Settings(profiles_dir=self.tmp / "profiles", ledger_path=self.tmp / "ledger.json",
                            cdp_url="http://x", auto_post=True)
        with mock.patch("uploader.uploaders.base.StealthBrowser"):
            FakeUploader(settings, self.ledger).upload(self.video)
        self.assertEqual(self.ledger.get_record(self.video, "youtube")["video_id"], "t9Z0Bku_itE")


class DeleteTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uploader = YouTubeUploader(Settings(ledger_path=self.tmp / "ledger.json"))

    def test_link_or_id_text(self):
        self.assertEqual(delete_youtube.resolve_video_id("https://youtu.be/t9Z0Bku_itE",
                                                         self.uploader), "t9Z0Bku_itE")

    def test_file_is_looked_up_in_the_ledger(self):
        video = self.tmp / "session10.mp4"
        video.write_bytes(b"lecture bytes")
        self.assertIsNone(delete_youtube.resolve_video_id(str(video), self.uploader))
        self.uploader.ledger.mark_uploaded(video, "youtube", extra={"video_id": "t9Z0Bku_itE"})
        self.assertEqual(delete_youtube.resolve_video_id(str(video), self.uploader), "t9Z0Bku_itE")


if __name__ == "__main__":
    unittest.main()
