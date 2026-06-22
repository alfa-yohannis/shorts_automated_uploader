"""Drive the IG create->reel flow step by step against the logged-in real Chrome
(CDP), dumping controls after each action so exact selectors can be read off.
STOPS before sharing. Run after a Chrome is up on the CDP port.

  ./venv/bin/python -m uploader.dev.probe_ig_flow --cdp http://127.0.0.1:9222
"""
import argparse

from uploader.browser import StealthBrowser
from uploader.config import Settings

VIDEO = "/home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4"

DUMP = r"""() => {
  const vis = el => el && el.offsetParent !== null;
  const out = []; const seen = new Set();
  const push = s => { if (s && !seen.has(s)) { seen.add(s); out.push(s); } };
  for (const el of document.querySelectorAll('[role=dialog]'))
    if (vis(el)) push('DIALOG aria-label="' + (el.getAttribute('aria-label')||'') + '"');
  for (const el of document.querySelectorAll('svg[aria-label]'))
    if (vis(el)) push('SVG  "' + el.getAttribute('aria-label') + '"');
  for (const el of document.querySelectorAll('button,[role=button],a[role=link],div[role=button]')) {
    if (!vis(el)) continue;
    const t=(el.innerText||'').trim().replace(/\s+/g,' ');
    if (t && t.length<28) push('BTN  "'+t+'"');
  }
  for (const el of document.querySelectorAll('input[type=file]'))
    push('FILE accept="'+(el.getAttribute('accept')||'')+'"');
  for (const el of document.querySelectorAll('textarea,[contenteditable=true],[role=textbox]'))
    if (vis(el)) push('EDIT '+el.tagName+' aria-label="'+(el.getAttribute('aria-label')||'')+'"');
  return out;
}"""


def dump(page, label):
    print(f"\n===== {label} =====", flush=True)
    try:
        for line in page.evaluate(DUMP):
            print("  " + line, flush=True)
    except Exception as e:
        print("  dump err:", e, flush=True)


def click_text(page, text, exact=True):
    loc = page.get_by_text(text, exact=exact)
    if loc.count() and loc.first.is_visible():
        loc.first.click()
        print(f"  -> clicked text '{text}'", flush=True)
        return True
    print(f"  -- text '{text}' not found", flush=True)
    return False


def click_role(page, name):
    loc = page.get_by_role("button", name=name)
    if loc.count() and loc.first.is_visible():
        loc.first.click()
        print(f"  -> clicked button '{name}'", flush=True)
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://127.0.0.1:9222")
    args = ap.parse_args()

    with StealthBrowser("instagram", Settings().profiles_dir, cdp_url=args.cdp) as b:
        page = b.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)

        page.locator('svg[aria-label="New post"]').first.click()
        page.wait_for_timeout(1500)
        dump(page, "1. create menu")

        click_text(page, "Post")
        page.wait_for_timeout(2500)
        dump(page, "2. file-select dialog")

        page.set_input_files("input[type=file]", VIDEO)
        page.wait_for_timeout(7000)
        dump(page, "3. after file (reels/crop)")

        # possible 'video shared as reels' OK dialog
        click_role(page, "OK") or click_text(page, "OK")
        page.wait_for_timeout(1500)

        # crop -> Next
        click_role(page, "Next") or click_text(page, "Next")
        page.wait_for_timeout(2500)
        dump(page, "4. edit/cover screen")

        # edit -> Next
        click_role(page, "Next") or click_text(page, "Next")
        page.wait_for_timeout(2500)
        dump(page, "5. caption/share screen (STOP — not sharing)")

        print("\nleaving tab open 60s; NOT sharing.", flush=True)
        page.wait_for_timeout(60000)


if __name__ == "__main__":
    main()
