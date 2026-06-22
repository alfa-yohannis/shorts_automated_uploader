"""Enumerate every switch/checkbox with its label + state, before and after
toggling 'Disclose post content'.

Run:  ./venv/bin/python -m uploader.dev.inspect_ai
"""
from uploader.browser import StealthBrowser
from uploader.config import Settings

VIDEO = "/home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4"

ENUM = r"""() => {
  function labelOf(el){
    let n = el;
    for (let i=0;i<6 && n;i++){
      n = n.parentElement; if(!n) break;
      const t=(n.innerText||'').trim();
      if(t && t.length<80) return t.replace(/\s+/g,' ');
    }
    return '';
  }
  const out=[];
  document.querySelectorAll('input[role=switch], button[role=switch]').forEach((s)=>{
    out.push('SWITCH checked='+s.getAttribute('aria-checked')+
             ' disabled='+(s.disabled||s.getAttribute('aria-disabled'))+
             ' | '+labelOf(s));
  });
  document.querySelectorAll('label.Checkbox__root').forEach((s)=>{
    out.push('CHECK checked='+s.getAttribute('aria-checked')+
             ' disabled='+s.getAttribute('aria-disabled')+
             ' | '+(s.innerText||'').trim().replace(/\s+/g,' ').slice(0,50));
  });
  return out;
}"""


def main():
    with StealthBrowser("tiktok", Settings().profiles_dir) as browser:
        page = browser.new_page()
        for _ in range(3):
            try:
                page.goto("https://www.tiktok.com/tiktokstudio/upload",
                          wait_until="domcontentloaded", timeout=45000)
                break
            except Exception as e:
                print("nav retry:", e, flush=True)
                page.wait_for_timeout(2000)
        page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
        page.set_input_files("input[type=file]", VIDEO)
        print("video selected; processing...", flush=True)
        page.wait_for_timeout(10000)

        page.locator("text=Show more").first.click()
        print("clicked Show more\n", flush=True)
        page.wait_for_timeout(2000)

        print("=== CONTROLS BEFORE ===", flush=True)
        for line in page.evaluate(ENUM):
            print("  " + line, flush=True)

        # toggle Disclose: click the switch whose label mentions Disclose
        sws = page.locator("input[role=switch]")
        n = sws.count()
        print(f"\nrole=switch inputs: {n}", flush=True)
        toggled = False
        for i in range(n):
            handle = sws.nth(i)
            lab = handle.evaluate(r"""el => {
                let n=el; for(let i=0;i<6&&n;i++){n=n.parentElement; if(!n)break;
                  const t=(n.innerText||'').trim(); if(t&&t.length<80) return t;} return '';}""")
            if "Disclose" in lab:
                handle.evaluate("el => { const lab = el.closest('label') || el.parentElement; lab.click(); }")
                print(f"toggled switch #{i} (label: {lab[:40]})", flush=True)
                toggled = True
                break
        if not toggled:
            print("Could not find Disclose switch by label", flush=True)
        page.wait_for_timeout(2500)

        print("\n=== CONTROLS AFTER DISCLOSE TOGGLE ===", flush=True)
        for line in page.evaluate(ENUM):
            print("  " + line, flush=True)

        print("\nwindow open 90s...", flush=True)
        page.wait_for_timeout(90000)


if __name__ == "__main__":
    main()
