"""Open the create flow up to the Crop screen, click the 'Select Crop' control,
and dump the aspect-ratio options (to find the 'Original' label). STOPS there.

  ./venv/bin/python -m uploader.dev.probe_ig_crop --cdp http://127.0.0.1:9222
"""
import argparse

from uploader.browser import StealthBrowser
from uploader.config import Settings

VIDEO = "/home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4"

DUMP = r"""() => {
  const vis = el => el && el.offsetParent !== null;
  const out=[]; const seen=new Set(); const push=s=>{if(s&&!seen.has(s)){seen.add(s);out.push(s);}};
  for (const el of document.querySelectorAll('svg[aria-label]')) if (vis(el)) push('SVG  "'+el.getAttribute('aria-label')+'"');
  for (const el of document.querySelectorAll('button,[role=button],div[role=button],[role=menuitem],[role=option]')) {
    if (!vis(el)) continue; const t=(el.innerText||'').trim().replace(/\s+/g,' ');
    if (t && t.length<28) push('BTN  "'+t+'"');
  }
  return out;
}"""


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
        page.get_by_text("Post", exact=True).first.click()
        page.wait_for_timeout(2000)
        page.set_input_files("input[type=file]", VIDEO)
        page.wait_for_timeout(7000)
        b_ok = page.get_by_role("button", name="OK")
        if b_ok.count() and b_ok.first.is_visible():
            b_ok.first.click(); page.wait_for_timeout(1200)

        print("\n=== CROP screen ===", flush=True)
        for line in page.evaluate(DUMP): print("  " + line, flush=True)

        # click the 'Select Crop' control (bottom-left)
        sc = page.locator('svg[aria-label="Select Crop"]')
        if sc.count():
            sc.first.click()
            page.wait_for_timeout(1200)
            print("\n=== after Select Crop (aspect options) ===", flush=True)
            for line in page.evaluate(DUMP): print("  " + line, flush=True)
        else:
            print("Select Crop control not found", flush=True)

        print("\nleaving open 45s (not posting)", flush=True)
        page.wait_for_timeout(45000)


if __name__ == "__main__":
    main()
