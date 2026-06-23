"""Discover YouTube Studio's real DOM by attaching to the logged-in real Chrome.

Run (attach to your real Chrome, signed into YouTube):
  ./venv/bin/python -m uploader.dev.inspect_youtube --chrome

It snapshots the controls every few seconds for ~2 minutes. Walk the upload
wizard (Create -> Upload videos -> pick a file -> Next ...) while it runs; each
snapshot prints the buttons / inputs / editables / radios visible at that moment,
so the real selectors can be read off and baked into YouTubeUploader.
"""
import argparse

from uploader.browser import StealthBrowser
from uploader.config import Settings

# Studio uses ytcp-*/tp-yt-* custom elements (light DOM) — dump ids + names too.
DUMP = r"""() => {
  const vis = el => el && el.offsetParent !== null;
  const out = []; const seen = new Set();
  const push = s => { if (s && !seen.has(s)) { seen.add(s); out.push(s); } };

  for (const el of document.querySelectorAll('ytcp-button,button,[role=button]')) {
    if (!vis(el)) continue;
    const t = (el.innerText||'').trim().replace(/\s+/g,' ');
    const id = el.id ? '#'+el.id : '';
    if (t && t.length < 30) push('BTN  "' + t + '" ' + id);
    else if (id) push('BTN  ' + id);
  }
  for (const el of document.querySelectorAll('input[type=file]')) {
    push('FILE accept="' + (el.getAttribute('accept')||'') + '"' + (el.id?(' #'+el.id):''));
  }
  for (const el of document.querySelectorAll('#textbox,[contenteditable=true],textarea')) {
    if (vis(el)) push('EDIT id="' + (el.id||'') + '" aria-label="' + (el.getAttribute('aria-label')||'') + '"');
  }
  for (const el of document.querySelectorAll('tp-yt-paper-radio-button,[role=radio]')) {
    if (vis(el)) push('RADIO name="' + (el.getAttribute('name')||'') + '" text="' + (el.innerText||'').trim().slice(0,40) + '"');
  }
  return out;
}"""


def snapshot(page, label):
    print(f"\n===== {label} =====", flush=True)
    try:
        for line in page.evaluate(DUMP):
            print("  " + line, flush=True)
    except Exception as e:
        print(f"  (dump failed: {e})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", action="store_true",
                    help="launch real Chrome on profiles/youtube and attach over CDP")
    ap.add_argument("--cdp", default=None, help="attach to a running Chrome, e.g. http://127.0.0.1:9222")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--snapshots", type=int, default=16)
    ap.add_argument("--interval", type=int, default=7)
    args = ap.parse_args()

    cid = Settings().yt_channel_id
    studio = f"https://studio.youtube.com/channel/{cid}" if cid else "https://studio.youtube.com/"

    cdp_url = args.cdp
    if args.chrome:
        from uploader.real_chrome import launch_with_cdp
        profile = Settings().profiles_dir / "youtube"
        cdp_url = launch_with_cdp(profile, port=args.port, url=studio)
        print(f"attached at {cdp_url}", flush=True)

    with StealthBrowser("youtube", Settings().profiles_dir, cdp_url=cdp_url) as browser:
        page = browser.new_page()
        page.goto(studio, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        snapshot(page, "STUDIO HOME (find the Create button)")
        for i in range(args.snapshots):
            snapshot(page, f"SNAPSHOT {i+1}/{args.snapshots} (walk the upload wizard now)")
            page.wait_for_timeout(args.interval * 1000)


if __name__ == "__main__":
    main()
