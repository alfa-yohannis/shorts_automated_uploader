"""Unit tests for the YouTube additions: video-id parsing, the playlist search query,
the 2 MB thumbnail guard, the slides/ cover fallback, the ledger's video_id fields,
how delete_youtube.py resolves its target, how the upload dialog is handed the file
again when Studio drops it, and the oEmbed check that confirms a publish. No browser,
no network; the thumbnail test needs ffmpeg and is skipped without it.
"""
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

import delete_youtube
from uploader import Settings, Ledger, UploadFailed, YouTubeUploader
from uploader.uploaders.base import VideoUploader
from uploader.uploaders.youtube import (THUMBNAIL_MAX_BYTES, parse_upload_fields,
                                        parse_video_id, served_by_oembed)

#: a youtube.txt as slides_narrator writes it, upload settings after KEYWORDS
NARRATOR_TXT = """TITLE
CQRS dan Event Sourcing | Arsitektur Perangkat Lunak

DESCRIPTION
Deskripsi kuliah.
#CQRS

KEYWORDS
CQRS, Event Sourcing

VIDEO
session10.mp4

PLAYLIST
Arsitektur Perangkat Lunak (Sofware Architecture)

LANGUAGE
Indonesian

CATEGORY
Education

LICENSE
creative_commons

VISIBILITY
public

MADE_FOR_KIDS
no

ALTERED_CONTENT
no

RECORDING_DATE
2026-11-14

COVER
slides/slide_01.png

SUBTITLES
session10.srt
"""


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


class UploadFieldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "slides").mkdir()
        (self.tmp / "slides" / "slide_01.png").write_bytes(b"img")
        (self.tmp / "session10.mp4").write_bytes(b"video")
        (self.tmp / "session10.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHalo\n")

    def test_reads_every_setting(self):
        self.assertEqual(parse_upload_fields(NARRATOR_TXT, self.tmp), {
            "video": self.tmp / "session10.mp4",
            "playlist": "Arsitektur Perangkat Lunak (Sofware Architecture)",
            "language": "Indonesian", "category": "Education",
            "license": "creative_commons", "visibility": "public",
            "made_for_kids": False, "altered_content": False,
            "recording_date": date(2026, 11, 14),
            "cover": self.tmp / "slides" / "slide_01.png",
            "subtitles": self.tmp / "session10.srt"})

    def test_settings_do_not_leak_into_the_tags(self):
        title, desc, tags = YouTubeUploader._parse_caption(NARRATOR_TXT)
        self.assertEqual(title, "CQRS dan Event Sourcing | Arsitektur Perangkat Lunak")
        self.assertEqual(tags, ["CQRS", "Event Sourcing"])
        self.assertTrue(desc.endswith("#CQRS"))

    def test_invalid_values_and_missing_cover_are_left_out(self):
        text = ("TITLE\nT\n\nLICENSE\nweird\n\nVISIBILITY\nsecret\n\n"
                "MADE_FOR_KIDS\nmaybe\n\nALTERED_CONTENT\nperhaps\n\n"
                "RECORDING_DATE\n14/11/2026\n\nVIDEO\ngone.mp4\n\n"
                "COVER\nnope.png\n\nSUBTITLES\nnone.srt\n")
        with mock.patch("builtins.print"):
            self.assertEqual(parse_upload_fields(text, self.tmp), {})

    def test_plain_caption_has_no_settings(self):
        self.assertEqual(parse_upload_fields("Title line\n\nBody\n\nkw1, kw2", self.tmp), {})


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


class ClockPage:
    """A page stand-in whose wait_for_timeout moves a fake clock forward."""

    def __init__(self):
        self.now = 0.0

    def wait_for_timeout(self, ms):
        self.now += ms / 1000


class SelectVideoTests(unittest.TestCase):
    """_select_video's decisions, with every browser step replaced by a stub."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uploader = YouTubeUploader(Settings(ledger_path=self.tmp / "ledger.json"))
        self.video = self.tmp / "session12.mp4"
        self.handed = []
        self.reloads = 0
        self.uploader._open_picker = lambda page: True
        self.uploader._hand_over = lambda page, video, how: self.handed.append(how)
        self.uploader._navigate = self._count_reload

    def _count_reload(self, page):
        self.reloads += 1

    def _outcomes(self, *outcomes):
        queue = list(outcomes)
        self.uploader._wait_for_details = lambda page: queue.pop(0)

    def test_a_dropped_file_is_handed_over_again_another_way(self):
        self._outcomes("not-taken", "details")
        with mock.patch("builtins.print"):
            self.uploader._select_video(None, self.video)
        self.assertEqual(self.handed, ["set the file", "reload and set the file"])
        self.assertEqual(self.reloads, 1)

    def test_every_way_dropped_stops_the_run(self):
        self._outcomes("not-taken", "not-taken", "not-taken")
        with mock.patch("builtins.print"), self.assertRaises(UploadFailed) as caught:
            self.uploader._select_video(None, self.video)
        self.assertEqual(self.handed, list(YouTubeUploader._SELECT_STRATEGIES))
        self.assertIn("safe to run again", str(caught.exception))

    def test_a_taken_file_is_never_handed_over_twice(self):
        self._outcomes("taken")
        with mock.patch("builtins.print"), self.assertRaises(UploadFailed) as caught:
            self.uploader._select_video(None, self.video)
        self.assertEqual(self.handed, ["set the file"])
        self.assertIn("draft", str(caught.exception))

    def test_a_dialog_that_never_opens_moves_to_the_next_way(self):
        ready = [False, True]
        self.uploader._open_picker = lambda page: ready.pop(0)
        self._outcomes("details")
        with mock.patch("builtins.print"):
            self.uploader._select_video(None, self.video)
        self.assertEqual(self.handed, ["reload and set the file"])


class WaitForDetailsTests(unittest.TestCase):
    """_wait_for_details against a fake clock that only the page's waits move."""

    def setUp(self):
        self.page = ClockPage()
        self.uploader = YouTubeUploader(
            Settings(ledger_path=Path(tempfile.mkdtemp()) / "ledger.json"))
        patcher = mock.patch("uploader.uploaders.youtube.time")
        fake_time = patcher.start()
        self.addCleanup(patcher.stop)
        fake_time.time.side_effect = lambda: self.page.now

    def _screen(self, title_from=None, button_until=None):
        """What is visible when: the title box from `title_from` seconds on (never
        when None), the "Select files" button until `button_until` seconds (always
        when None)."""
        def visible(page, selector_csv):
            if selector_csv == YouTubeUploader._TITLE_BOX:
                return title_from is not None and page.now >= title_from
            return button_until is None or page.now < button_until
        self.uploader._visible = visible

    def test_the_title_box_means_details(self):
        self._screen(title_from=5, button_until=2)
        self.assertEqual(self.uploader._wait_for_details(self.page), "details")
        self.assertLess(self.page.now, 10)

    def test_a_button_that_stays_means_not_taken(self):
        self._screen()
        self.assertEqual(self.uploader._wait_for_details(self.page), "not-taken")
        self.assertGreaterEqual(self.page.now, YouTubeUploader._NOT_TAKEN_AFTER_S)

    def test_a_button_that_goes_without_a_form_means_taken(self):
        self._screen(button_until=3)
        self.assertEqual(self.uploader._wait_for_details(self.page), "taken")
        self.assertGreaterEqual(self.page.now, 3 + YouTubeUploader._DETAILS_AFTER_TAKEN_S)


class PublishedCheckTests(unittest.TestCase):
    """The oEmbed check that confirms a publish Studio's dialog text did not show,
    and the retry advice once Studio holds a video."""

    @staticmethod
    def _reply(body: bytes):
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.return_value = body
        return reply

    def test_a_title_from_oembed_means_served(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=self._reply(b'{"title": "Kuliah"}')) as urlopen:
            self.assertTrue(served_by_oembed("https://youtu.be/W3klAHSsmUQ"))
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("youtu.be%2FW3klAHSsmUQ", urlopen.call_args[0][0])

    def test_refusals_are_asked_again_then_give_false(self):
        refusal = urllib.error.HTTPError("u", 401, "Unauthorized", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=refusal) as urlopen, \
                mock.patch("time.sleep") as sleep:
            self.assertFalse(served_by_oembed("https://youtu.be/W3klAHSsmUQ", tries=3))
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_retry_advice_warns_once_studio_holds_a_video(self):
        uploader = YouTubeUploader(Settings(ledger_path=Path(tempfile.mkdtemp()) / "l.json"))
        self.assertEqual(uploader.retry_note(), "safe to retry")
        uploader.video_url = "https://youtu.be/W3klAHSsmUQ"
        self.assertIn("https://youtu.be/W3klAHSsmUQ", uploader.retry_note())
        self.assertIn("second copy", uploader.retry_note())


if __name__ == "__main__":
    unittest.main()
