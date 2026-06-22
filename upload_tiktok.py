"""Step 2: Upload a video to TikTok using the saved stealth profile.

Run:  ./venv/bin/python upload_tiktok.py <video.mp4> [caption.txt|"caption"] [cover.png] [--post] [--force]

- caption: a "literal string" or a path to a .txt file (its contents are used)
- cover:   optional image; if omitted, a sibling <video-name>.png/.jpg is auto-used
- --post:  click the Post button automatically (hands-off); otherwise it waits for you
- --force: upload even if the ledger says it was already posted

Requires profiles/tiktok/ (create it with: python login.py tiktok).
Other config knobs (disclose_ai, portrait_glob) live in uploader/config.py.
Thin CLI shim over uploader.TikTokUploader.
"""
import argparse
import sys
from pathlib import Path

from uploader import TikTokUploader, Settings, UploadSkipped, AlreadyUploaded, LoginRequired


def main():
    ap = argparse.ArgumentParser(description="Upload a video to TikTok.")
    ap.add_argument("video")
    ap.add_argument("caption", nargs="?", default="", help='.txt path or literal caption')
    ap.add_argument("cover", nargs="?", default=None, help="cover image (else sibling auto-detected)")
    ap.add_argument("--post", action="store_true",
                    help="click Post automatically (hands-off); otherwise it waits for you")
    ap.add_argument("--force", action="store_true", help="upload even if ledger says already posted")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    uploader = TikTokUploader(settings=Settings(auto_post=args.post))
    caption = uploader.resolve_caption(args.caption) if args.caption else ""
    cover = uploader.resolve_cover(video, args.cover)
    print(f"Cover: {cover if cover else '(none / will use a video frame)'}", flush=True)

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


if __name__ == "__main__":
    main()
