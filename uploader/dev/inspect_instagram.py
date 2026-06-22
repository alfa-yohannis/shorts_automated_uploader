"""Discover Instagram's real DOM by attaching to the logged-in real Chrome.

Run (attach to your real Chrome, logged in):
  ./venv/bin/python -m uploader.dev.inspect_instagram --chrome

It snapshots the controls every few seconds for ~2 minutes. Open the create
flow (click New post -> pick the video -> Next ...) while it runs; each snapshot
prints the buttons / aria-labels / inputs / editables visible at that moment, so
the real selectors can be read off and baked into InstagramUploader.
"""
import argparse
import time

from uploader.browser import StealthBrowser
from uploader.config import Settings

# Rich dump: clickable text, aria-labels, file inputs, editables, dialog roles.
DUMP = r"""() => {
  const vis = el => el && el.offsetParent !== null;
  const out = [];
  const seen = new Set();
  const push = s => { if (s && !seen.has(s)) { seen.add(s); out.push(s); } };

  for (const el of document.querySelectorAll('[role=dialog]')) {
    if (vis(el)) push('DIALOG present (aria-label="' + (el.getAttribute('aria-label')||'') + '")');
  }
  for (const el of document.querySelectorAll('svg[aria-label]')) {
    if (vis(el)) push('SVG  "' + el.getAttribute('aria-label') + '"');
  }
  for (const el of document.querySelectorAll('button,[role=button],a[role=link],div[role=button]')) {
    if (!vis(el)) continue;
    const t = (el.innerText||'').trim().replace(/\s+/g,' ');
    if (t && t.length < 30) push('BTN  "' + t + '"');
  }
  for (const el of document.querySelectorAll('input[type=file]')) {
    push('FILE accept="' + (el.getAttribute('accept')||'') + '" multiple=' + el.multiple);
  }
  for (const el of document.querySelectorAll('textarea,[contenteditable=true],[role=textbox]')) {
    if (vis(el)) push('EDIT tag=' + el.tagName + ' aria-label="' + (el.getAttribute('aria-label')||'') + '"');
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
                    help="launch real Chrome on profiles/instagram and attach over CDP")
    ap.add_argument("--cdp", default=None, help="attach to a running Chrome, e.g. http://127.0.0.1:9222")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--snapshots", type=int, default=16)
    ap.add_argument("--interval", type=int, default=7)
    args = ap.parse_args()

    cdp_url = args.cdp
    if args.chrome:
        from uploader.real_chrome import launch_with_cdp
        profile = Settings().profiles_dir / "instagram"
        cdp_url = launch_with_cdp(profile, port=args.port, url="https://www.instagram.com/")
        print(f"attached at {cdp_url}", flush=True)

    with StealthBrowser("instagram", Settings().profiles_dir, cdp_url=cdp_url) as browser:
        page = browser.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        snapshot(page, "HOME (find the New post button)")

        # best-effort auto-open of the create dialog so step 1 selectors surface
        for sel in ['svg[aria-label="New post"]', 'a:has(svg[aria-label="New post"])',
                    'svg[aria-label="Create"]', 'a:has(svg[aria-label="Create"])']:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                print(f"\nclicked: {sel}", flush=True)
                page.wait_for_timeout(2000)
                break

        for i in range(args.snapshots):
            snapshot(page, f"SNAPSHOT {i+1}/{args.snapshots} (click through the flow now)")
            page.wait_for_timeout(args.interval * 1000)


if __name__ == "__main__":
    main()
