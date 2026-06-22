"""Load upload page, select video, open Edit cover, dump the modal.

Run:  ./venv/bin/python -m uploader.dev.inspect_cover
"""
from uploader.browser import StealthBrowser
from uploader.config import Settings

VIDEO = "/home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4"


def main():
    with StealthBrowser("tiktok", Settings().profiles_dir) as browser:
        page = browser.new_page()
        page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded")
        page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
        page.set_input_files("input[type=file]", VIDEO)
        print("video selected; processing...", flush=True)
        page.wait_for_timeout(12000)

        page.locator("text=Edit cover").first.click()
        print("clicked Edit cover; waiting for modal...", flush=True)
        page.wait_for_timeout(4000)

        inputs = page.locator("input[type=file]")
        print(f"\n=== file inputs after opening modal: {inputs.count()} ===", flush=True)
        for i in range(inputs.count()):
            print(f"  [{i}] accept={inputs.nth(i).get_attribute('accept')}", flush=True)

        js = """() => {
          const out = [];
          for (const el of document.querySelectorAll('button, div, span, [role=button], [role=tab]')) {
            const t = (el.innerText||'').trim();
            if (t && /upload|unggah|select cover|sampul|frame/i.test(t) && t.length < 40) {
              out.push(el.tagName + ' | "' + t + '" | class=' + (el.className||'').toString().slice(0,50));
            }
          }
          return [...new Set(out)].slice(0, 25);
        }"""
        print("\n=== modal buttons (upload/select) ===", flush=True)
        for line in page.evaluate(js):
            print("  " + line, flush=True)

        print("\nwindow open 60s...", flush=True)
        page.wait_for_timeout(60000)


if __name__ == "__main__":
    main()
