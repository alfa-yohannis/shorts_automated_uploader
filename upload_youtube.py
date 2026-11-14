"""Step 2 (YouTube): Upload a Short or a landscape video to YouTube Studio.

Drive your real, logged-in Chrome (Google bot-detects automated logins):

  # attach to a copy of your logged-in Chrome profile (recommended, like Instagram)
  ./venv/bin/python upload_youtube.py <video.mp4> [caption.txt|"caption"] [cover.png] --chrome

  # a narrated lecture from slides_narrator: youtube.txt as the caption, the first
  # slide (slides/slide_01.png) as the cover, into a playlist, in Indonesian
  ./venv/bin/python upload_youtube.py videos/session10/session10.mp4 \
      videos/session10/youtube.txt --chrome --playlist "<playlist title>" --language Indonesian

  # or a persistent stealth profile you logged into once (python login.py youtube)
  ./venv/bin/python upload_youtube.py <video.mp4> [caption.txt|"caption"] [cover.png]

  # or attach to a Chrome you started yourself with --remote-debugging-port
  ./venv/bin/python upload_youtube.py <video.mp4> ... --cdp http://127.0.0.1:9222

Caption .txt -> first line = title, last line = keywords (comma-separated),
everything in between = description.
--post publishes automatically; otherwise it stops on the Visibility step for you.
Thin CLI shim over uploader.YouTubeUploader.
"""
import argparse
import sys
from pathlib import Path

from uploader import YouTubeUploader, Settings, UploadSkipped, AlreadyUploaded, LoginRequired


def main():
    ap = argparse.ArgumentParser(description="Upload a video to YouTube.")
    ap.add_argument("video")
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
    ap.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public",
                    help="video visibility on publish (default public)")
    ap.add_argument("--made-for-kids", action="store_true",
                    help="mark the video as 'made for kids' (default: not made for kids)")
    ap.add_argument("--channel", default=Settings().yt_channel_id,
                    help="YouTube channel id to upload to (default: the configured channel)")
    ap.add_argument("--playlist", default=None,
                    help="exact title of a playlist on the channel to add the video to")
    ap.add_argument("--language", default=None,
                    help="video language as Studio lists it, e.g. Indonesian "
                         "(default: from the _en/_id file suffix)")
    args = ap.parse_args()

    video = Path(args.video).resolve()
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

    settings = Settings(cdp_url=cdp_url, auto_post=args.post, yt_channel_id=args.channel,
                        yt_visibility=args.visibility, yt_made_for_kids=args.made_for_kids,
                        yt_playlist=args.playlist, yt_language=args.language)
    uploader = YouTubeUploader(settings=settings)
    caption = uploader.resolve_caption(args.caption) if args.caption else ""
    cover = uploader.resolve_cover(video, args.cover)
    print(f"Thumbnail: {cover if cover else '(none / YouTube picks a frame)'}", flush=True)

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
    if uploader.video_url:
        print(f"Video URL: {uploader.video_url}")


if __name__ == "__main__":
    main()
