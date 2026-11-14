"""Delete a video from YouTube Studio (on the configured channel's account).

  # dry run: opens the delete dialog, prints what it names, then cancels
  ./venv/bin/python delete_youtube.py <video-id | youtu.be link | video.mp4> --chrome

  # delete for real
  ./venv/bin/python delete_youtube.py <video-id | youtu.be link | video.mp4> --chrome --yes

A local video file is looked up in the ledger, which keeps the video id of every
YouTube upload recorded since upload_youtube.py started reading the video link.
A deleted video's ledger record is removed, so the file can be uploaded again.
Thin CLI shim over uploader.YouTubeUploader.delete.
"""
import argparse
import sys
from pathlib import Path

from uploader import YouTubeUploader, Settings, LoginRequired
from uploader.uploaders.youtube import parse_video_id


def resolve_video_id(target: str, uploader: YouTubeUploader) -> str | None:
    """The video id `target` names: the ledger's video_id for an existing local file,
    otherwise an id parsed from the text. Returns None when neither yields one."""
    path = Path(target)
    if path.is_file():
        record = uploader.ledger.get_record(path, platform=uploader.site) or {}
        return record.get("video_id")
    return parse_video_id(target)


def main():
    ap = argparse.ArgumentParser(description="Delete a video from YouTube.")
    ap.add_argument("target", help="video id, youtu.be / watch?v= link, or an uploaded video file")
    ap.add_argument("--yes", action="store_true",
                    help="really delete; without it the run is a dry run that cancels")
    ap.add_argument("--chrome", action="store_true",
                    help="launch real Chrome on profiles/youtube and attach over CDP")
    ap.add_argument("--cdp", metavar="URL", default=None,
                    help="attach to an already-running Chrome, e.g. http://127.0.0.1:9222")
    ap.add_argument("--port", type=int, default=9222, help="CDP port for --chrome (default 9222)")
    ap.add_argument("--channel", default=Settings().yt_channel_id,
                    help="channel whose Studio is opened by --chrome (default: the configured one)")
    args = ap.parse_args()

    uploader = YouTubeUploader(settings=Settings(yt_channel_id=args.channel))
    video_id = resolve_video_id(args.target, uploader)
    if not video_id:
        print(f"No video id in {args.target!r}. A file must be in the ledger with a video_id; "
              "otherwise pass the id or the youtu.be link.")
        sys.exit(1)

    cdp_url = args.cdp
    if args.chrome:
        from uploader.real_chrome import launch_with_cdp
        profile = uploader.settings.profiles_dir / "youtube"
        if not profile.exists():
            print(f"Expected a logged-in profile at {profile} (seed it: ./init_youtube_profile.sh).")
            sys.exit(1)
        print(f"Launching real Chrome on {profile} with CDP on :{args.port} ...", flush=True)
        cdp_url = launch_with_cdp(profile, port=args.port,
                                  url=f"https://studio.youtube.com/channel/{args.channel}")
        print(f"Attached at {cdp_url}", flush=True)
    uploader.settings.cdp_url = cdp_url

    print(f"Video: https://youtu.be/{video_id}", flush=True)
    try:
        deleted = uploader.delete(video_id, confirm=args.yes)
    except LoginRequired as e:
        print(e)
        sys.exit(1)
    sys.exit(0 if deleted or not args.yes else 1)


if __name__ == "__main__":
    main()
