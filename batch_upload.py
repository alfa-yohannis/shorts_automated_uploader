"""Batch-upload portrait Reels/TikToks from a target folder, on a schedule.

Scans a folder for portrait videos (``*_portrait_*.mp4`` — both the English
``_en`` and Indonesian ``_id`` variants), groups them by pattern, and uploads
the ones the ledger says are NOT yet posted — to TikTok and Instagram.

Designed to be run unattended (cron, 3x/day): it auto-posts and, by default,
publishes ONE pattern (its ``_en`` + ``_id``) per platform per run, so the
backlog drains as a steady, detection-friendly drip. Already-uploaded videos
are skipped via the per-platform ledger, so re-runs never double-post.

Each video uses its sibling ``<name>.txt`` as the caption and ``<name>.png`` as
the cover (auto-detected by the uploader).

  ./venv/bin/python batch_upload.py                       # 1 pattern, both platforms, auto-post
  ./venv/bin/python batch_upload.py --limit 3             # 3 patterns this run
  ./venv/bin/python batch_upload.py --platforms tiktok    # one platform only
  ./venv/bin/python batch_upload.py --dry-run             # show what WOULD upload
  ./venv/bin/python batch_upload.py --no-post             # stop at Post/Share (manual click)
"""
import argparse
import fnmatch
import subprocess
import sys
import time
from pathlib import Path

from uploader import (
    Settings, Ledger, TikTokUploader, InstagramUploader,
    UploadSkipped, AlreadyUploaded, LoginRequired,
)

DEFAULT_DIR = "/home/alfa/pCloudDrive/target"
LANGS = ("en", "id")          # variant suffixes that share a pattern
PLATFORMS = ("tiktok", "instagram")
IG_CDP_PORT = 9222


def _file_date(path: Path) -> float:
    """Best-effort creation time: the filesystem birthtime if exposed (rare on
    Linux/FUSE such as the pCloud mount), else the modification time — the closest
    reliable proxy for when a generated file was created."""
    st = path.stat()
    return getattr(st, "st_birthtime", None) or st.st_mtime


def discover(target: Path, portrait_glob: str, order: str = "created"):
    """Return {pattern_key: {lang: video_path}} for portrait videos.

    order: "created" = oldest file first (default, so the backlog drains in the
    order videos were produced), "created-desc" = newest first, "name" =
    alphabetical by pattern. A pattern's date is its earliest en/id file."""
    patterns: dict[str, dict[str, Path]] = {}
    for mp4 in target.glob("*.mp4"):
        if not fnmatch.fnmatch(mp4.name.lower(), portrait_glob):
            continue
        stem = mp4.stem
        base, _, lang = stem.rpartition("_")
        lang = lang.lower()
        if lang not in LANGS:
            base, lang = stem, ""        # ungrouped (no _en/_id) — keep on its own
        patterns.setdefault(base, {})[lang or stem] = mp4

    def group_date(variants):            # earliest file in the en/id group
        return min(_file_date(v) for v in variants.values())

    if order == "name":
        items = sorted(patterns.items())
    else:
        items = sorted(patterns.items(), key=lambda kv: group_date(kv[1]),
                       reverse=(order == "created-desc"))
    return dict(items)


def caption_for(video: Path) -> str:
    txt = video.with_suffix(".txt")
    return txt.read_text(encoding="utf-8").strip() if txt.exists() else ""


def select_patterns(patterns, platforms, ledger, force, limit):
    """Pick the first `limit` patterns that still have un-uploaded work on any
    requested platform. Returns [(pattern_key, {lang: video})]."""
    chosen = []
    for key, variants in patterns.items():
        pending = any(
            force or not ledger.is_uploaded(v, platform=p)
            for v in variants.values() for p in platforms
        )
        if pending:
            chosen.append((key, variants))
        if limit and len(chosen) >= limit:
            break
    return chosen


def upload_one(uploader, video: Path, force: bool) -> str:
    """Run a single upload; return a short status string. Never raises."""
    try:
        caption = caption_for(video)
        cover = uploader.resolve_cover(video, None)
        posted = uploader.upload(video, caption=caption, cover=cover, force=force)
        return "POSTED" if posted else "NOT-CONFIRMED"
    except AlreadyUploaded:
        return "already-uploaded"
    except UploadSkipped as e:
        return f"skipped ({e})"
    except LoginRequired as e:
        return f"LOGIN-REQUIRED ({e})"
    except Exception as e:                       # keep the batch going
        return f"ERROR ({type(e).__name__}: {e})"


def run_tiktok(selected, auto_post, force):
    results = []
    for key, variants in selected:
        for lang in sorted(variants):
            video = variants[lang]
            if not force and Ledger(Settings().ledger_path).is_uploaded(video, "tiktok"):
                results.append((video.name, "already-uploaded")); continue
            up = TikTokUploader(settings=Settings(auto_post=auto_post))
            status = upload_one(up, video, force)
            results.append((video.name, status))
            print(f"  [tiktok] {video.name}: {status}", flush=True)
    return results


def run_instagram(selected, auto_post, force):
    # Anything to do? (avoid launching Chrome for nothing)
    todo = [
        variants[lang] for _key, variants in selected for lang in sorted(variants)
        if force or not Ledger(Settings().ledger_path).is_uploaded(variants[lang], "instagram")
    ]
    if not todo:
        print("  [instagram] nothing pending.", flush=True)
        return []

    from uploader.real_chrome import launch_with_cdp
    profile = Settings().profiles_dir / "instagram"
    if not profile.exists():
        print(f"  [instagram] no profile at {profile} — run ./init_instagram_profile.sh", flush=True)
        return [(v.name, "LOGIN-REQUIRED (no profile)") for v in todo]

    print(f"  [instagram] launching real Chrome on {profile} (CDP :{IG_CDP_PORT}) ...", flush=True)
    results = []
    try:
        cdp_url = launch_with_cdp(profile, port=IG_CDP_PORT, url="https://www.instagram.com/")
        settings = Settings(cdp_url=cdp_url, auto_post=auto_post)
        for video in todo:
            up = InstagramUploader(settings=settings)
            status = upload_one(up, video, force)
            results.append((video.name, status))
            print(f"  [instagram] {video.name}: {status}", flush=True)
    finally:
        # close the CDP Chrome so the next run can relaunch cleanly
        subprocess.run(["pkill", "-f", str(profile.resolve())],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    return results


def main():
    ap = argparse.ArgumentParser(description="Batch-upload portrait videos to TikTok + Instagram.")
    ap.add_argument("--dir", default=DEFAULT_DIR, help=f"folder to scan (default {DEFAULT_DIR})")
    ap.add_argument("--platforms", default="tiktok,instagram",
                    help="comma list: tiktok,instagram (default both)")
    ap.add_argument("--limit", type=int, default=1,
                    help="max patterns (each = en+id) to upload this run; 0 = no limit (default 1)")
    ap.add_argument("--order", choices=["created", "created-desc", "name"], default="created",
                    help="pattern order: created=oldest file first (default), "
                         "created-desc=newest first, name=alphabetical")
    ap.add_argument("--no-post", action="store_true",
                    help="do NOT auto-click Post/Share (waits for a manual click); "
                         "a manual share is NOT recorded in the ledger (re-runnable)")
    ap.add_argument("--force", action="store_true", help="upload even if the ledger says posted")
    ap.add_argument("--dry-run", action="store_true", help="list what would upload, then exit")
    args = ap.parse_args()

    target = Path(args.dir).expanduser()
    if not target.is_dir():
        print(f"Target folder not found: {target}"); sys.exit(1)

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip() in PLATFORMS]
    if not platforms:
        print(f"No valid platforms in '{args.platforms}'. Choose from {PLATFORMS}."); sys.exit(1)

    auto_post = not args.no_post
    ledger = Ledger(Settings().ledger_path)
    patterns = discover(target, Settings().portrait_glob, order=args.order)
    if not patterns:
        print(f"No portrait videos ({Settings().portrait_glob}) in {target}."); sys.exit(0)

    selected = select_patterns(patterns, platforms, ledger, args.force, args.limit)
    print(f"== batch_upload == {target}", flush=True)
    print(f"   patterns found: {len(patterns)} | selected this run: {len(selected)} "
          f"| order: {args.order} | platforms: {','.join(platforms)} | auto_post: {auto_post}", flush=True)

    if not selected:
        print("Nothing new to upload — every selected pattern is already in the ledger.", flush=True)
        sys.exit(0)

    for key, variants in selected:
        langs = ", ".join(f"{lang}:{v.name}" for lang, v in sorted(variants.items()))
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(min(_file_date(v) for v in variants.values())))
        print(f"   • [{when}] {key}  ({langs})", flush=True)

    if args.dry_run:
        print("DRY RUN — nothing uploaded.", flush=True)
        sys.exit(0)

    summary = {}
    if "tiktok" in platforms:
        print("\n-- TikTok --", flush=True)
        summary["tiktok"] = run_tiktok(selected, auto_post, args.force)
    if "instagram" in platforms:
        print("\n-- Instagram --", flush=True)
        summary["instagram"] = run_instagram(selected, auto_post, args.force)

    print("\n== summary ==", flush=True)
    for platform, rows in summary.items():
        posted = sum(1 for _, s in rows if s == "POSTED")
        print(f"   {platform}: {posted}/{len(rows)} newly posted", flush=True)
        for name, status in rows:
            print(f"      {name}: {status}", flush=True)


if __name__ == "__main__":
    main()
