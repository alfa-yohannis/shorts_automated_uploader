"""Step 2 (YouTube): Upload a Short or a landscape video to YouTube Studio.

Drive your real, logged-in Chrome (Google bot-detects automated logins):

  # attach to a copy of your logged-in Chrome profile (recommended, like Instagram)
  ./venv/bin/python upload_youtube.py <video.mp4> [caption.txt|"caption"] [cover.png] --chrome

  # a narrated lecture from slides_narrator: its youtube.txt names the video and
  # carries the title, description (with chapters), keywords and every upload
  # setting (PLAYLIST, LANGUAGE, CATEGORY, LICENSE, VISIBILITY, MADE_FOR_KIDS,
  # ALTERED_CONTENT, RECORDING_DATE, COVER, SUBTITLES), so it is the only argument
  ./venv/bin/python upload_youtube.py videos/session10/youtube.txt --chrome --post

A flag given on the command line overrides the matching youtube.txt setting.

  # or a persistent stealth profile you logged into once (python login.py youtube)
  ./venv/bin/python upload_youtube.py <video.mp4> [caption.txt|"caption"] [cover.png]

  # or attach to a Chrome you started yourself with --remote-debugging-port
  ./venv/bin/python upload_youtube.py <video.mp4> ... --cdp http://127.0.0.1:9222

Caption .txt -> first line = title, last line = keywords (comma-separated),
everything in between = description; or TITLE / DESCRIPTION / KEYWORDS blocks.
--post publishes automatically; otherwise it stops on the Visibility step for you.
Thin CLI shim over uploader.YouTubeUploader.
"""
import argparse
import sys
from pathlib import Path

from uploader import (YouTubeUploader, Settings, UploadSkipped, AlreadyUploaded,
                      LoginRequired, UploadFailed)
from uploader.uploaders.youtube import parse_upload_fields


def parse_args() -> argparse.Namespace:
    """The command line; every metadata flag defaults to None so that a
    youtube.txt setting can fill it in."""
    ap = argparse.ArgumentParser(description="Upload a video to YouTube.")
    ap.add_argument("video", help="the video file, or a youtube.txt whose VIDEO names it")
    ap.add_argument("caption", nargs="?", default="", help='.txt path or literal caption')
    ap.add_argument("cover", nargs="?", default=None, help="thumbnail image (else sibling auto-detected)")
    ap.add_argument("--force", action="store_true", help="upload even if ledger says already posted")
    ap.add_argument("--chrome", action="store_true",
                    help="launch real Chrome on profiles/youtube and attach over CDP")
    ap.add_argument("--cdp", metavar="URL", default=None,
                    help="attach to an already-running Chrome, e.g. http://127.0.0.1:9222")
    ap.add_argument("--port", type=int, default=9222, help="CDP port for --chrome (default 9222)")
    ap.add_argument("--post", action="store_true",
                    help="click Publish automatically (hands-off); otherwise it waits for you")
    ap.add_argument("--visibility", choices=["public", "unlisted", "private"], default=None,
                    help="video visibility on publish (default: youtube.txt VISIBILITY, else public)")
    ap.add_argument("--license", choices=["creative_commons", "standard"], default=None,
                    help="video license (default: youtube.txt LICENSE, else the configured one)")
    ap.add_argument("--made-for-kids", action="store_true",
                    help="mark the video as 'made for kids' (default: youtube.txt MADE_FOR_KIDS, else no)")
    ap.add_argument("--altered-content", action="store_true",
                    help="answer Yes to the altered or synthetic content question "
                         "(default: youtube.txt ALTERED_CONTENT, else No)")
    ap.add_argument("--channel", default=Settings().yt_channel_id,
                    help="YouTube channel id to upload to (default: the configured channel)")
    ap.add_argument("--playlist", default=None,
                    help="exact title of a playlist on the channel to add the video to "
                         "(default: youtube.txt PLAYLIST)")
    ap.add_argument("--language", default=None,
                    help="video language as Studio lists it, e.g. Indonesian "
                         "(default: youtube.txt LANGUAGE, else the _en/_id file suffix)")
    ap.add_argument("--category", default=None,
                    help="category as Studio lists it, e.g. Education (default: youtube.txt CATEGORY)")
    ap.add_argument("--subtitles", default=None,
                    help="an .srt uploaded as subtitles in the video language "
                         "(default: youtube.txt SUBTITLES)")
    return ap.parse_args()


def main():
    args = parse_args()

    # `upload_youtube.py youtube.txt [cover]`: the metadata file names the video
    metadata_first = args.video.lower().endswith(".txt")
    caption_arg = args.video if metadata_first else args.caption
    cover_cli = (args.caption or args.cover) if metadata_first else args.cover
    caption = YouTubeUploader.resolve_caption(caption_arg) if caption_arg else ""
    caption_file = Path(caption_arg) if caption_arg and Path(caption_arg).is_file() else None
    if metadata_first:
        if caption_file is None:
            print(f"Metadata file not found: {args.video}")
            sys.exit(1)
        fields = parse_upload_fields(caption, caption_file.resolve().parent)
        if "video" not in fields:
            print(f"{args.video} has no VIDEO block naming an existing video file.")
            sys.exit(1)
        video = fields["video"].resolve()
    else:
        video = Path(args.video).resolve()
        base_dir = caption_file.resolve().parent if caption_file else video.parent
        fields = parse_upload_fields(caption, base_dir)
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    cdp_url = args.cdp
    if args.chrome:
        from uploader.real_chrome import launch_with_cdp
        profile = Settings().profiles_dir / "youtube"
        if not profile.exists():
            print(f"Expected a logged-in profile at {profile} "
                  "(seed it from your real Chrome, or run: python login.py youtube).")
            sys.exit(1)
        print(f"Launching real Chrome on {profile} with CDP on :{args.port} ...", flush=True)
        start_url = f"https://studio.youtube.com/channel/{args.channel}" if args.channel else "https://studio.youtube.com/"
        cdp_url = launch_with_cdp(profile, port=args.port, url=start_url)
        print(f"Attached at {cdp_url}", flush=True)

    # a command-line flag wins over youtube.txt, which wins over Settings' defaults
    defaults = Settings()
    subtitles = Path(args.subtitles).resolve() if args.subtitles else fields.get("subtitles")
    settings = Settings(
        cdp_url=cdp_url, auto_post=args.post, yt_channel_id=args.channel,
        yt_visibility=args.visibility or fields.get("visibility", defaults.yt_visibility),
        yt_made_for_kids=args.made_for_kids or fields.get("made_for_kids", defaults.yt_made_for_kids),
        yt_altered_content=args.altered_content or fields.get("altered_content", False),
        yt_playlist=args.playlist or fields.get("playlist"),
        yt_language=args.language or fields.get("language"),
        yt_category=args.category or fields.get("category"),
        yt_license=args.license or fields.get("license", defaults.yt_license),
        yt_recording_date=fields.get("recording_date"),
        yt_subtitles=subtitles,
    )
    uploader = YouTubeUploader(settings=settings)
    cover_arg = cover_cli or (str(fields["cover"]) if "cover" in fields else None)
    cover = uploader.resolve_cover(video, cover_arg)
    print(f"Video: {video}", flush=True)
    print(f"Upload settings: visibility={settings.yt_visibility}, "
          f"playlist={settings.yt_playlist or '-'}, language={settings.yt_language or '-'}, "
          f"category={settings.yt_category or '-'}, license={settings.yt_license}, "
          f"made_for_kids={'yes' if settings.yt_made_for_kids else 'no'}, "
          f"altered_content={'yes' if settings.yt_altered_content else 'no'}, "
          f"recording_date={settings.yt_recording_date or 'today'}", flush=True)
    print(f"Thumbnail: {cover if cover else '(none / YouTube picks a frame)'}", flush=True)
    print(f"Subtitles: {settings.yt_subtitles or '-'}", flush=True)

    try:
        uploader.upload(video, caption=caption, cover=cover, force=args.force)
    except AlreadyUploaded as e:
        print(f"✓ {e}")     # already done — informational, not an error
        sys.exit(0)
    except UploadSkipped as e:
        print(f"SKIP: {e}")
        sys.exit(0)
    except LoginRequired as e:
        print(e)
        sys.exit(1)
    except UploadFailed as e:
        print(f"FAILED: {e}", flush=True)
        sys.exit(1)
    if uploader.video_url:
        print(f"Video URL: {uploader.video_url}")


if __name__ == "__main__":
    main()
