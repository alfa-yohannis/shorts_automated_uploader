"""Step 2 (Instagram): Upload a Reel.

Run (attach to your real Chrome — recommended on Linux/KDE):
  ./venv/bin/python upload_instagram.py <video.mp4> [caption.txt|"caption"] [cover.png] --chrome

Or attach to a Chrome you already started with --remote-debugging-port:
  ./venv/bin/python upload_instagram.py <video.mp4> ... --cdp http://127.0.0.1:9222

Or use a saved stealth profile (rarely works for IG — keyring/captcha):
  ./venv/bin/python upload_instagram.py <video.mp4> ...

--chrome launches real Chrome on profiles/instagram (a copy of a trusted,
logged-in profile) so its keyring-encrypted session decrypts, then drives it.
"""
import argparse
import sys
from pathlib import Path

from uploader import InstagramUploader, Settings, UploadSkipped, AlreadyUploaded, LoginRequired


def main():
    ap = argparse.ArgumentParser(description="Upload a Reel to Instagram.")
    ap.add_argument("video")
    ap.add_argument("caption", nargs="?", default="", help='.txt path or literal caption')
    ap.add_argument("cover", nargs="?", default=None, help="cover image (else sibling auto-detected)")
    ap.add_argument("--force", action="store_true", help="upload even if ledger says already posted")
    ap.add_argument("--chrome", action="store_true",
                    help="launch real Chrome on profiles/instagram and attach over CDP")
    ap.add_argument("--cdp", metavar="URL", default=None,
                    help="attach to an already-running Chrome, e.g. http://127.0.0.1:9222")
    ap.add_argument("--port", type=int, default=9222, help="CDP port for --chrome (default 9222)")
    ap.add_argument("--post", action="store_true",
                    help="click Share automatically (hands-off); otherwise it waits for you")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    cdp_url = args.cdp
    if args.chrome:
        from uploader.real_chrome import launch_with_cdp
        profile = Settings().profiles_dir / "instagram"
        if not profile.exists():
            print(f"Expected a trusted profile copy at {profile} (see README §Instagram).")
            sys.exit(1)
        print(f"Launching real Chrome on {profile} with CDP on :{args.port} ...", flush=True)
        cdp_url = launch_with_cdp(profile, port=args.port,
                                  url="https://www.instagram.com/")
        print(f"Attached at {cdp_url}", flush=True)

    settings = Settings(cdp_url=cdp_url, auto_post=args.post)
    uploader = InstagramUploader(settings=settings)
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
