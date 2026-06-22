# Automated Browser — TikTok + Instagram Reels Video Uploader

Drives a **real Google Chrome** via Playwright to upload videos to **TikTok** and
**Instagram Reels** with a caption and a custom cover/thumbnail (plus the
**AI-generated content** disclosure on TikTok). You log in by hand **once** per
platform; the session is reused after. A ledger prevents the same video from
being posted twice. Object-oriented: logic lives in the `uploader/` package,
with thin CLI shims at the root.

Instagram needs a different approach than TikTok — it attaches to your **real
Chrome over CDP** (see [§13](#13-instagram-reels)) because its session can't be
reused by a Playwright-launched browser on this machine.

> Working directory: `/data1/projects/shorts_automated_uploader`
> Python: 3.12 · Playwright 1.60 · runs on Linux/X11 (`DISPLAY=:0`)

---

## 1. Current status (June 2026)

| Capability | State |
|---|---|
| Manual login + persistent session | ✅ working (`login.py`) |
| Bot-detection bypass for login | ✅ real Chrome + persistent profile + stealth |
| Upload video | ✅ |
| Insert long caption (from `.txt`) | ✅ |
| Custom cover/thumbnail (from `.png`) | ✅ |
| "AI-generated content" disclosure toggle | ✅ (auto-confirms the "Turn on" dialog) |
| Open maximized on the 2nd monitor | ✅ (`StealthBrowser` + `Monitor.pick`) |
| Upload ledger — never re-upload | ✅ (`ledger.py`, keyed by content hash) |
| Portrait-only rule (`*_portrait_*.mp4`) | ✅ |
| Auto-click **Post / Share** | ⏸ available but OFF by default (`auto_post=False`) |
| **Instagram Reels** | ✅ working via **attach-to-real-Chrome (CDP)** — see [§13](#13-instagram-reels) |
| &nbsp;&nbsp;↳ aspect ratio → Original + custom cover | ✅ |
| Batch upload a whole folder | ✅ `batch_upload.py` (en+id → both platforms, ledger-aware) — see [§15](#15-batch-upload--scheduling) |
| Scheduled drip-posting (cron) | ✅ `batch_upload.sh` at 5am/11am/5pm — see [§15](#15-batch-upload--scheduling) |

**Decisions still pending from the user**
- Whether to flip `auto_post=True` for hands-off posting (works on both platforms).
- Whether to build `batch_upload.py` for the whole `target/` folder.

---

## 2. Why it's built this way (anti-detection)

TikTok **blocks login** on Playwright's default bundled Chromium (it detects
`navigator.webdriver` and the `--enable-automation` flag). The combination that
**works** lives in [`uploader/browser.py`](uploader/browser.py):

1. **Real Google Chrome**, not bundled Chromium — `channel="chrome"`.
2. **Persistent profile** per site — `launch_persistent_context(user_data_dir=profiles/<site>)`.
   The login lives inside the Chrome profile, exactly like a normal browser.
3. **Strip automation flags** — `args=["--disable-blink-features=AutomationControlled", ...]`
   and `ignore_default_args=["--enable-automation"]`.
4. **Stealth JS patches** — `playwright_stealth.Stealth().apply_stealth_sync(context)`
   (spoofs `navigator.webdriver`, plugins, etc.).
5. **Manual login** — a human solves password/2FA/captcha; far less detectable than
   scripted credential entry.

If TikTok ever blocks again, the next escalation is **QR-code login** (scan with the
phone app) which sidesteps web detection almost entirely.

---

## 3. Running on a fresh machine (full setup)

This app is meant to run on a **desktop Linux machine with a visible screen** (it
drives a real, on-screen Chrome). Everything below is what a brand-new machine
needs. Nothing in `profiles/` or `ledger.json` is committed (they're your logins
and history — gitignored), so a fresh clone starts clean and you log in there.

### 3.1 System prerequisites

| Need | Why | Check / install |
|---|---|---|
| **Linux with a graphical session** (X11/Wayland-X) | Chrome opens a real, interactive window | `echo $DISPLAY` → must print something (e.g. `:0`) |
| **Google Chrome** (stable) | We drive it via `channel="chrome"` — *not* bundled Chromium | `google-chrome --version` (install from google.com/chrome) |
| **Python 3.12** + venv | runtime | `python3 --version`; `sudo apt install python3-venv` if missing |
| **git, rsync, curl** | clone; Instagram profile copy; CDP readiness check | `sudo apt install git rsync curl` |
| `xrandr` *(optional)* | picks the 2nd monitor; falls back to 1920×1080 if absent | `sudo apt install x11-xserver-utils` |

> No `playwright install` step is needed — we use the system Google Chrome, so the
> bundled Chromium browser binary is never downloaded.

### 3.2 Install

```bash
git clone <your-repo-url> shorts_automated_uploader
cd shorts_automated_uploader
./setup.sh          # venv + pip deps + creates profiles/ and sessions/
```

Manual equivalent:
```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
mkdir -p profiles sessions
```

Everything runs through the venv interpreter: **`./venv/bin/python <script>.py`**,
and GUI runs need the display: prefix with **`DISPLAY=:0`** (match your `$DISPLAY`).

### 3.3 Per-platform login (do once on the new machine)

Each platform has a one-time **`init_*_profile.sh`** helper that wraps the steps
below (guards the venv, handles re-runs safely). Honors `DISPLAY` and `MONITOR`.

- **TikTok** — simple, built in:
  ```bash
  ./init_tiktok_profile.sh                 # or: DISPLAY=:0 ./venv/bin/python login.py tiktok
  ```
  Opens a real Chrome at TikTok's login; log in by hand. It polls for the
  `sessionid` cookie and saves the session to `profiles/tiktok/`. Done. Re-prompts
  before overwriting an existing profile.

- **Instagram** — needs the real-Chrome/CDP setup (IG won't reuse a Playwright
  profile). Seed the profile, then log in once:
  ```bash
  ./init_instagram_profile.sh              # seeds profiles/instagram/ from Chrome "Default"
  ./init_instagram_profile.sh "Profile 3"  # …or from a named Chrome profile
  ```
  **Chrome must be closed** during the copy (the script refuses if it's running).
  Then run an upload with `--chrome` and log into Instagram in that window if it
  opens logged-out. Full details in **[§13](#13-instagram-reels)**.

### 3.4 Smoke-test without uploading

```bash
./venv/bin/python -c "import uploader; print('package OK:', uploader.__all__)"
DISPLAY=:0 ./venv/bin/python list_uploaded.py   # empty ledger on a fresh machine
```

---

## 4. How to use (TikTok)

> Instagram has its own procedure — see [§13](#13-instagram-reels).

### Step 1 — log in once
```bash
DISPLAY=:0 ./venv/bin/python login.py tiktok
```
A real Chrome window opens at the login page. Log in by hand. The script polls for
the `sessionid` cookie and exits the moment you're in. Session is stored in
`profiles/tiktok/` — **never needs to be repeated** unless you log out.

### Step 2 — upload a video
```bash
DISPLAY=:0 ./venv/bin/python upload_tiktok.py \
    <video_portrait_*.mp4> [caption.txt|"caption"] [cover.png] [--post] [--force]
```
- **Arg 1** — the video (`*_portrait_*.mp4` only, else it's skipped).
- **Arg 2** *(optional)* — a `.txt` file (its contents become the caption) **or** a
  literal `"caption string"`. If omitted, no caption.
- **Arg 3** *(optional)* — a cover image. If omitted, a sibling `<video-name>.png/.jpg`
  is auto-detected and used.
- **`--post`** *(optional flag)* — click Post automatically (hands-off); otherwise it
  waits ~2 min for you to click.
- **`--force`** *(optional flag)* — upload even if the ledger says it was already posted.

The window opens **maximized on the 2nd monitor**, does video → caption → AI toggle →
cover, then **waits for you to click Post** (2-min window). Pass `--post` (or set
`auto_post=True` in [`uploader/config.py`](uploader/config.py)) to click Post automatically.

### Step 3 — see what's been uploaded
```bash
./venv/bin/python list_uploaded.py
```

---

## 5. Layout & file-by-file

The logic lives in the **`uploader/`** package (object-oriented); the root
scripts are thin CLI shims that drive it.

```
uploader/
├── config.py            Settings dataclass (auto_post, disclose_ai, portrait_glob, paths, cdp_url)
├── browser.py           StealthBrowser (launch OR attach-over-CDP) + Monitor
├── ledger.py            Ledger class (SHA-256 content hash → record)
├── auth.py              LoginManager (manual login per site)
├── real_chrome.py       launch real Chrome with a DevTools port (for CDP attach)
├── uploaders/
│   ├── base.py          VideoUploader — abstract template-method base
│   ├── tiktok.py        TikTokUploader — TikTok Studio implementation
│   └── instagram.py     InstagramUploader — Reels via CDP-attached real Chrome
└── dev/
    ├── inspect_ai.py        TikTok AI-toggle selector probe
    ├── inspect_cover.py     TikTok cover-modal selector probe
    ├── inspect_instagram.py IG DOM snapshotter (CDP-aware)
    ├── probe_ig_flow.py     drives the IG create→share flow, dumps each stage
    └── probe_ig_crop.py     dumps the IG crop/aspect-ratio options
login.py · upload_tiktok.py · upload_instagram.py · list_uploaded.py   ← thin CLI entry points
batch_upload.py          batch-upload a whole folder (en+id → both platforms), ledger-aware
setup.sh                 fresh-clone setup (venv + deps)
init_tiktok_profile.sh · init_instagram_profile.sh   ← one-time login/profile setup
batch_upload.sh          cron wrapper for batch_upload.py (DISPLAY/XAUTHORITY/lock — see §15)
tests/                   unit tests (stdlib unittest — see §14)
```

| Module / class | Purpose |
|---|---|
| [`uploader/config.py`](uploader/config.py) → `Settings` | Tunable knobs (`auto_post`, `disclose_ai`, `portrait_glob`, `cdp_url`) and resolved paths (`profiles_dir`, `ledger_path`). Override per-call, e.g. `Settings(auto_post=True)`. |
| [`uploader/browser.py`](uploader/browser.py) → `StealthBrowser`, `Monitor` | Context manager with two modes: **launch** (own stealth real-Chrome profile, used by TikTok) or **attach** (`cdp_url` → connect to a running Chrome over CDP, used by Instagram). `Monitor.pick()` reads `xrandr` for the 2nd monitor (falls back to 1st). |
| [`uploader/ledger.py`](uploader/ledger.py) → `Ledger` | Upload tracking, **one list per platform** (`{platform: {hash: record}}`). `is_uploaded(path, platform)`, `mark_uploaded()`, `get_record()`, `list_records()`, `video_key()`. Auto-migrates the old single-list format. Data in `ledger.json`. |
| [`uploader/auth.py`](uploader/auth.py) → `LoginManager` | One-time manual login (TikTok). Polls for the `sessionid` cookie, then exits. |
| [`uploader/real_chrome.py`](uploader/real_chrome.py) → `launch_with_cdp()` | Launches the real Google Chrome with a DevTools port (+ `--remote-allow-origins`, non-default user-data-dir) so Playwright can attach. Used by Instagram. |
| [`uploader/uploaders/base.py`](uploader/uploaders/base.py) → `VideoUploader` | Abstract base. `upload()` runs the rules (portrait, ledger, login/CDP guard) + lifecycle + records on success; `_run_steps()` is the overridable order. Raises `UploadSkipped` / `LoginRequired`. |
| [`uploader/uploaders/tiktok.py`](uploader/uploaders/tiktok.py) → `TikTokUploader` | TikTok Studio steps + selectors (see §7). |
| [`uploader/uploaders/instagram.py`](uploader/uploaders/instagram.py) → `InstagramUploader` | Instagram Reels steps + selectors (see §13). Overrides `_run_steps` (IG takes the cover before the caption). |
| [`uploader/dev/`](uploader/dev/) | **Dev tools.** TikTok: `inspect_ai`, `inspect_cover`. Instagram: `inspect_instagram`, `probe_ig_flow`, `probe_ig_crop`. Rerun to rediscover selectors when a site changes its UI. |
| [`login.py`](login.py) · [`upload_tiktok.py`](upload_tiktok.py) · [`upload_instagram.py`](upload_instagram.py) · [`list_uploaded.py`](list_uploaded.py) | Thin CLI shims over the package. |
| [`batch_upload.py`](batch_upload.py) | Scan a folder, group each pattern's `_en`+`_id`, upload the not-yet-posted ones to both platforms. Ledger-aware, auto-posts, `--limit` per run. See §15. |
| `init_tiktok_profile.sh` · `init_instagram_profile.sh` | One-time profile/login setup (wrap `login.py tiktok` / the IG seed-from-Chrome copy). See §3.3 / §13.1. |
| `batch_upload.sh` · `setup.sh` | Shell helpers. `batch_upload.sh` is the cron wrapper (sets `DISPLAY`/`XAUTHORITY`, `flock` lock); `setup.sh` builds the venv. |
| `profiles/<site>/` | Chrome user-data dir per platform = **your login**. Treat like a password; gitignored. |
| `sessions/` | **Obsolete.** Leftover from an earlier `storage_state.json` approach before we switched to persistent profiles. Gitignored. |
| `requirements.txt` | Pinned deps. |

---

## 6. The upload pipeline

`VideoUploader.upload()` is the **template method** in
[`uploader/uploaders/base.py`](uploader/uploaders/base.py) — it runs the rules and
lifecycle; `TikTokUploader` ([`tiktok.py`](uploader/uploaders/tiktok.py)) supplies the
per-platform steps (`_navigate`, `_select_video`, `_set_caption`,
`_enable_ai_disclosure`, `_set_cover`, `_post`).

In order:

1. **Rule 1 — portrait only**: `is_portrait()` checks `fnmatch(name, settings.portrait_glob)`.
   Non-matching → raises `UploadSkipped` (CLI prints SKIP, exit 0).
2. **Rule 2 — no re-uploads**: `ledger.is_uploaded(video, "tiktok")`. Already posted →
   raises `UploadSkipped` with the date (unless `force=True`).
3. **Login guard**: no `profiles/tiktok/` → raises `LoginRequired`.
4. **Launch** `StealthBrowser` (real Chrome, 2nd monitor); `_navigate` goes to
   `https://www.tiktok.com/tiktokstudio/upload` (retries up to 3× for `ERR_ABORTED`).
5. **Select video** — `set_input_files` on the hidden `input[type=file]`
   (wait `state="attached"`, it's never "visible").
6. **Caption** — click `div[contenteditable=true]`, select-all + delete, then
   `keyboard.insert_text(caption)` (instant; typing char-by-char times out on long text).
7. **AI disclosure** (`_enable_ai_disclosure`, when `settings.disclose_ai`) — click
   `text=Show more`, find the `input[role=switch]` whose parent text starts with
   "AI-generated content", click its `[class*=Switch__root]`, then confirm via **"Turn on"**.
8. **Cover** (`_set_cover`) — click `text=Edit cover`, `set_input_files` on the modal's
   `input[accept*="image"]`, confirm via the **"Save"** button.
9. **Post** (`_post`) — `settings.auto_post` clicks the **Post** button; otherwise it waits
   and lets you click. Either way `_wait_for_success()` watches for a redirect to
   `tiktokstudio/content` or a success dialog.
10. **Record** — on confirmed post, `ledger.mark_uploaded()`. If not confirmed, nothing
    is recorded (safe to retry).

---

## 7. Hard-won TikTok Studio selectors

These took live DOM inspection to find. **TikTok changes its upload UI often** — when
something breaks, rerun the `uploader.dev.inspect_*` tools to rediscover.

| Element | Selector / flow | Notes |
|---|---|---|
| Video input | `input[type=file]` | Hidden — wait `state="attached"`, not visible. |
| Caption box | `div[contenteditable=true]` | DraftJS editor. Use `keyboard.insert_text`, not `.type()`. |
| Show advanced | `text=Show more` | Reveals disclosure toggles. |
| AI-gen toggle | `input[role=switch]` whose climbed parent text starts `AI-generated content` | State is in the **visual thumb** class `Switch__thumb--checked-true`, **not** `aria-checked`. Click the `[class*=Switch__root]`. |
| AI confirm dialog | button **"Turn on"** | Pops up after enabling. |
| Edit cover | `text=Edit cover` → modal | |
| Cover image input | `input[accept*="image"]` (inside the cover modal) | accepts `image/jpeg, image/png, image/jpg`. |
| Cover confirm | button **"Save"** | |
| Post button | button **"Post"** (exact) | **Disabled until the video finishes processing** — `--post` waits up to 3 min for it to enable, else clicking does nothing and closing pops a "Leave site?" prompt. |
| "Continue to post?" check | button **"Post now"** (exact) | Safety-check dialog ("We're still checking your video…") that can appear a few seconds *after* clicking Post; the wait loop clicks **Post now** whenever it shows. |
| Post success | URL contains `tiktokstudio/content`, or text like "Manage posts" / "uploaded to TikTok" | |

The 4 switches under "Show more" (in order): `High-quality uploads` (disabled),
`Disclose post content`, `AI-generated content`, `Content check lite`. The
**AI-generated content** switch is independent — you do **not** need to enable
"Disclose post content" first.

---

## 8. Ledger & rules

- **`ledger.json`** is keyed **by platform, then by content hash**:
  ```json
  {
    "tiktok":    { "<sha256>": {name, path, caption_preview, first_uploaded, last_uploaded} },
    "instagram": { "<sha256>": {...} }
  }
  ```
  So each platform has its own list. A video posted to Instagram but **not** TikTok
  is "already uploaded" for IG yet still uploads to TikTok (`is_uploaded(video, "tiktok")`
  only checks the `tiktok` list).
- Hash key means a renamed/moved file is still recognized as already-posted.
- A video is recorded **only on a confirmed post** — both manual click and `--post`
  are detected by the uploader's `_wait_for_success()`.
- **Re-uploading the same video** to a platform it's already on prints a confirmation
  and exits 0 (it's not an error): `✓ '<name>' has already been successfully uploaded
  to <platform> (on <date>) — nothing to do. Pass --force to upload it again.`
  In code this is the `AlreadyUploaded` exception (a subclass of `UploadSkipped`).
- `--force` bypasses the skip for intentional re-uploads.
- **Portrait rule**: `portrait_glob = "*_portrait_*.mp4"` in
  [`uploader/config.py`](uploader/config.py). Change it there if the naming convention changes.
- Old single-list ledgers (`{hash: {…, platforms:[…]}}`) are **auto-migrated** to the
  per-platform layout on load.

To manually mark a video as already posted (e.g. one posted before the ledger existed):
```bash
./venv/bin/python -c "from uploader import Ledger, Settings; from pathlib import Path; \
  Ledger(Settings().ledger_path).mark_uploaded(Path('/path/to/video_portrait_id.mp4'), 'tiktok')"
```

---

## 9. Multi-monitor

`Monitor.pick()` parses `xrandr --listmonitors` and returns the geometry of the
**2nd** monitor if present, else the 1st. Detected layout:
- `eDP-1` (laptop, primary) `1920x1080+0+0`
- `HDMI-1` (external) `1920x1080+1920+0` ← window opens here, maximized

The window is positioned with `--window-position=x,y --window-size=w,h` and
`no_viewport=True` so the page fills it.

---

## 10. Gotchas / operational notes

- **One process per profile.** Chrome refuses to open a profile that's already in use
  ("Opening in existing browser session"). Kill stragglers before relaunching:
  ```bash
  pkill -f "profiles/tiktok"      # returns exit 144 — harmless, it matches its own shell
  ```
- **First navigation `ERR_ABORTED`** on a fresh profile is common → the code retries 3×.
- **GUI runs need `DISPLAY=:0`** and should be launched as background jobs (the window is
  interactive and long-lived).
- **Long captions**: `.type()` at 30ms/char exceeds Playwright's 30s action timeout on
  ~2000-char captions → use `keyboard.insert_text` (already done).
- **Caption length**: TikTok may truncate very long captions. Your `.txt` files include a
  trailing YouTube-style keyword block that TikTok doesn't use — trim if needed.
- **`Date.now()`/random** restrictions only apply to the orchestration layer, not these
  standalone scripts — `time`/`hashlib` are used freely in `uploader/ledger.py`.

---

## 11. TODO / next steps

1. **Decide `auto_post`** — set `auto_post=True` in
   [`uploader/config.py`](uploader/config.py) for hands-off posting (both platforms).
2. ~~**`batch_upload.py`**~~ — ✅ **built** (see [§15](#15-batch-upload--scheduling)):
   scans the folder, groups each pattern's `_en`+`_id`, skips ledger entries, and
   uploads to both platforms. Runs on cron via `batch_upload.sh`.
3. **IG success text** — `_wait_for_success` matches "...has been shared"; if a run
   posts but isn't recorded, rerun `probe_ig_flow` past Share to capture exact text.
4. **Caption trimming** — optionally strip the trailing keyword block for TikTok.

---

## 12. Quick reference

```bash
# --- one-time profile setup ---
./init_tiktok_profile.sh                                     # TikTok login (wraps login.py)
./init_instagram_profile.sh ["Profile 3"]                   # seed IG profile from real Chrome (Chrome CLOSED)

# --- batch (a whole folder, ledger-aware) ---
./batch_upload.sh --dry-run                                  # show what the next run would post
./batch_upload.sh [--limit N] [--platforms tiktok,instagram] [--no-post] [--force]

# --- TikTok ---
DISPLAY=:0 ./venv/bin/python login.py tiktok                 # login once
DISPLAY=:0 ./venv/bin/python upload_tiktok.py <video.mp4> [caption.txt|"text"] [cover.png] [--post] [--force]

# --- Instagram Reels (attaches to real Chrome; see §13) ---
DISPLAY=:0 ./venv/bin/python upload_instagram.py <video.mp4> [caption.txt|"text"] [cover.png] --chrome [--post] [--force]

# see uploaded history
./venv/bin/python list_uploaded.py

# free a stuck profile lock
pkill -f "profiles/tiktok"          # or profiles/instagram

# rediscover selectors if a site's UI changes
DISPLAY=:0 ./venv/bin/python -m uploader.dev.inspect_ai
DISPLAY=:0 ./venv/bin/python -m uploader.dev.inspect_cover
DISPLAY=:0 ./venv/bin/python -m uploader.dev.probe_ig_flow --cdp http://127.0.0.1:9222
```

Config flags live in [`uploader/config.py`](uploader/config.py) (`Settings`):
`auto_post` (False), `disclose_ai` (True), `portrait_glob` (`*_portrait_*.mp4`), `cdp_url` (None).

---

## 13. Instagram Reels

Instagram **cannot** be driven the way TikTok is. A Playwright-launched Chrome lands
**logged-out** (its session cookies are encrypted with the OS keyring — Chrome
"v11" — which only your *real* Chrome can read), and logging in fresh hits an
**endless captcha** on a no-history profile. The fix: **attach Playwright to your
real Chrome over the DevTools protocol (CDP)** so it drives your already-logged-in,
keyring-backed session.

`upload_instagram.py --chrome` automates this: it launches the real Google Chrome on
`profiles/instagram/` with a debugging port (using a non-default user-data-dir — Chrome
136+ blocks debugging on the default one — plus `--remote-allow-origins=*`), waits for
the endpoint, then `connect_over_cdp`.

### 13.1 One-time setup on a new machine

You need `profiles/instagram/` to be a Chrome profile that can log into Instagram
**without** the captcha wall. Best source: a copy of an **established** Chrome
profile (one with real browsing history).

**Scripted (recommended):** [`init_instagram_profile.sh`](init_instagram_profile.sh)
does the copy below for you — it refuses to run while Chrome is open, lists the
available profiles if you name a missing one, and prompts before overwriting:

```bash
./init_instagram_profile.sh                 # seeds from Chrome "Default"
./init_instagram_profile.sh "Profile 3"     # …or from a named profile
```

**Manual equivalent** (what the script runs):

```bash
# 1. find your established Chrome profiles and their accounts
./venv/bin/python - <<'PY'
import json, os
p = os.path.expanduser("~/.config/google-chrome/Local State")
for k, v in json.load(open(p))["profile"]["info_cache"].items():
    print(k, "→", v.get("name"), v.get("user_name"))
PY

# 2. copy an established profile into profiles/instagram (Chrome must be CLOSED)
#    replace "Profile 3" with the one you picked above
SRC="$HOME/.config/google-chrome"
mkdir -p profiles/instagram
cp "$SRC/Local State" "profiles/instagram/Local State"
rsync -a --exclude Cache --exclude 'Code Cache' --exclude GPUCache --exclude DawnCache \
  --exclude GraphiteDawnCache --exclude 'Service Worker/CacheStorage' \
  --exclude component_crx_cache --exclude extensions_crx_cache --exclude Crashpad \
  "$SRC/Profile 3/" profiles/instagram/Default/
```

Then run an upload with `--chrome`. **If the window opens logged-out** (common when
the keyring can't be read on the new machine), just **log into Instagram once in that
window** — because the login is saved without a working keyring it persists as a
decryptable "v10" cookie, so every later run stays logged in. An established-profile
copy usually clears the captcha.

> Don't have a logged-in desktop Chrome to copy? Create an empty `profiles/instagram/`,
> run with `--chrome`, and log in in the window — but a brand-new profile may get
> captcha-walled. Logging in via **"Log in with Facebook"** tends to work.

### 13.2 Upload a Reel

```bash
DISPLAY=:0 ./venv/bin/python upload_instagram.py \
    <video_portrait_*.mp4> [caption.txt|"caption"] [cover.png] --chrome [--post] [--force]
```
- `--chrome` — launch real Chrome on `profiles/instagram` and attach (the normal way).
- `--cdp http://127.0.0.1:9222` — instead attach to a Chrome you already started.
- `--post` — click **Share** automatically (hands-off). Without it, the flow stops at
  Share and waits ~2 min for **you** to click (and still records once it detects the post).
- Same positional args / `--force` / portrait rule / ledger as TikTok.

It runs: **New post → Post → select video → crop set to *Original* → cover via
*Select From Computer* → caption → Share**, then records the post in the ledger.
The final Share uses an **exact** match so it never hits the "Share to" / "Share to
Facebook" controls on the same screen.

### 13.3 If Instagram changes its UI

Re-discover selectors against the logged-in session (Chrome must be up on the CDP port):
```bash
DISPLAY=:0 ./venv/bin/python -m uploader.dev.probe_ig_flow --cdp http://127.0.0.1:9222
DISPLAY=:0 ./venv/bin/python -m uploader.dev.probe_ig_crop --cdp http://127.0.0.1:9222
```
then update the selector constants in [`uploader/uploaders/instagram.py`](uploader/uploaders/instagram.py).

---

## 14. Tests

Unit tests live in [`tests/`](tests/) and use the stdlib `unittest` — **no extra
dependencies, no browser, no network**. They cover the `Ledger` (per-platform lists,
content-hash dedup, old-format migration), `Settings`, the portrait/caption/cover
rules, and the `upload()` guards (`AlreadyUploaded` / `UploadSkipped` / `LoginRequired`,
plus a mocked-browser success path that records to the ledger).

```bash
./venv/bin/python -m unittest discover -s tests -v     # run everything
./venv/bin/python -m unittest tests.test_ledger        # one module
```

(They also run under `pytest` if you install it, but it isn't required.)

---

## 15. Batch upload & scheduling

[`batch_upload.py`](batch_upload.py) uploads a whole folder, unattended. It scans
`--dir` (default `/home/alfa/pCloudDrive/target`) for `*_portrait_*.mp4`, groups
each pattern's **`_en` + `_id`** variants together, and uploads the ones the ledger
says aren't posted yet — to **both TikTok and Instagram**. Each video uses its
sibling `.txt` as the caption and `.png` as the cover (auto-detected).

It **auto-posts** by default (cron can't click for you) and, by default, publishes
**one pattern per run** (`--limit 1`) so a backlog drains as a steady, detection-
friendly drip. Already-uploaded videos are skipped via the per-platform ledger, so
re-runs never double-post.

```bash
./batch_upload.sh --dry-run                  # show what the next run WOULD post
./batch_upload.sh                            # 1 pattern (en+id) → both platforms, auto-post
./batch_upload.sh --limit 3                  # 3 patterns this run
./batch_upload.sh --platforms tiktok         # one platform only
./batch_upload.sh --no-post                  # stop at Post/Share for a manual click
./batch_upload.sh --force                    # ignore the ledger (intentional re-upload)
```

Per run it does the TikTok uploads first (each in its own stealth Chrome), then
launches the real Chrome once over CDP for the Instagram uploads and **kills it
afterward** so the next run starts clean. One video failing doesn't abort the rest;
a summary prints at the end.

### 15.1 The cron wrapper

`batch_upload.py` needs a GUI (real Chrome on screen), but cron starts with no
environment — so run it through [`batch_upload.sh`](batch_upload.sh), which:
- sets `DISPLAY` (`:0`), `XAUTHORITY` (`~/.Xauthority`) and `MONITOR` (1) — without
  these, Chrome can't draw and the run dies;
- logs to `logs/cron.log`;
- holds an `flock` single-instance lock so an 11:00 run can't collide with a 05:00
  run that's still going.

Any extra args pass straight through to `batch_upload.py`.

### 15.2 Schedule (5am / 11am / 5pm)

Installed via `crontab -e`:

```cron
0 5,11,17 * * * DISPLAY=:0.0 XAUTHORITY=/home/alfa/.Xauthority /home/alfa/projects/shorts_automated_uploader/batch_upload.sh >> /home/alfa/projects/shorts_automated_uploader/logs/cron.log 2>&1
```

With `--limit 1`, that posts up to **3 patterns/day** to each platform. Watch a run
live with `tail -f logs/cron.log`, or trigger one supervised by hand:
`DISPLAY=:0 ./batch_upload.sh --limit 1`.

---

## 16. Worked examples (copy-paste)

Real commands against `/home/alfa/pCloudDrive/target/`. Each video uses its sibling
`.txt` (caption) and `.png` (cover, auto-detected).

**One-time setup (per machine):**
```bash
./setup.sh                                  # venv + deps
./init_tiktok_profile.sh                    # TikTok login
./init_instagram_profile.sh                 # seed IG profile (Chrome CLOSED), then log in once
```

**Upload a single video to TikTok:**
```bash
DISPLAY=:0 ./venv/bin/python upload_tiktok.py \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.mp4 \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.txt --post
```

**Upload a single Reel to Instagram** (`--chrome` attaches to your real Chrome):
```bash
DISPLAY=:0 ./venv/bin/python upload_instagram.py \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.mp4 \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.txt --chrome --post
```

**Re-post a video that's already in the ledger** — add `--force` (otherwise it skips
with "already uploaded"). Example: re-post the Indonesian Reel to Instagram:
```bash
DISPLAY=:0 ./venv/bin/python upload_instagram.py \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.mp4 \
    /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.txt --chrome --post --force
```
> `--force` updates the existing record's `last_uploaded`; it does **not** create a
> duplicate ledger entry. Drop `--post` from any command to stop at Post/Share and
> click it yourself.

**Batch (a whole folder, ledger-aware):**
```bash
./batch_upload.sh --dry-run                  # preview what the next run would post
./batch_upload.sh --limit 1                  # post 1 pattern (en+id) to both platforms
./batch_upload.sh --limit 1 --platforms instagram   # IG only
./batch_upload.sh --force --limit 1          # re-post even if the ledger has them
```

**Check / manage history:**
```bash
./venv/bin/python list_uploaded.py           # dump the ledger
```
