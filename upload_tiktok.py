"""Step 2: Upload a video to TikTok using the saved stealth profile.

Run:  ./venv/bin/python upload_tiktok.py <video.mp4> [caption.txt|"caption"] [cover.png] [--force]

- caption: a "literal string" or a path to a .txt file (its contents are used)
- cover:   optional image; if omitted, a sibling <video-name>.png/.jpg is auto-used
- --force: upload even if the ledger says it was already posted

Config knobs (auto_post, disclose_ai, portrait_glob) live in uploader/config.py.
Thin CLI shim over uploader.TikTokUploader.
"""
import sys
from pathlib import Path

from uploader import TikTokUploader, UploadSkipped, LoginRequired


def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in flags

    if not pos:
        print('Usage: python upload_tiktok.py <video.mp4> [caption.txt|"caption"] [cover.png] [--force]')
        sys.exit(1)

    video = Path(pos[0]).resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        sys.exit(1)

    uploader = TikTokUploader()
    caption = uploader.resolve_caption(pos[1]) if len(pos) > 1 else ""
    cover = uploader.resolve_cover(video, pos[2] if len(pos) > 2 else None)
    print(f"Cover: {cover if cover else '(none / will use a video frame)'}", flush=True)

    try:
        uploader.upload(video, caption=caption, cover=cover, force=force)
    except UploadSkipped as e:
        print(f"SKIP: {e}")
        sys.exit(0)
    except LoginRequired as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
