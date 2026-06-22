# Automated Browser — TikTok (and later Reels) Video Uploader

Drives a **real Google Chrome** via Playwright to upload videos to TikTok with a
caption, a custom cover/thumbnail, and the **AI-generated content** disclosure
turned on. You log in by hand **once**; the session is reused forever after. A
ledger prevents the same video from ever being posted twice.

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
| Auto-click **Post** | ⏸ available but OFF by default (`auto_post=False`) |
| Instagram Reels | ❌ not built yet (login.py already supports `instagram` session) |
| Batch upload a whole folder | ❌ not built yet (planned — see TODO) |

**Decisions still pending from the user**
- Whether to flip `auto_post=True` for hands-off posting.
- Whether the adapter-pattern test video was actually *posted* (if so, it should be
  marked in the ledger so it isn't re-uploaded).
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

## 3. Setup from scratch

```bash
cd /data1/projects/shorts_automated_uploader

# 1. one-shot: venv + deps + runtime dirs
./setup.sh

# 2. system needs Google Chrome + an X display
google-chrome --version        # Chrome 149 confirmed present
echo $DISPLAY                  # must be set (we use :0)
```

`setup.sh` is what you run after a **fresh clone** — `venv/`, `profiles/`,
`sessions/` and `ledger.json` are all gitignored (the profiles hold your live
login — treat like a password), so the script rebuilds the runtime bits. Manual
equivalent if you'd rather:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
# No `playwright install` — we drive the system Google Chrome (channel="chrome").
```

Everything is run through the venv interpreter: **`./venv/bin/python <script>.py`**.

---

## 4. How to use

### Step 1 — log in once (per platform)
```bash
DISPLAY=:0 ./venv/bin/python login.py tiktok       # or: instagram
```
A real Chrome window opens at the login page. Log in by hand. The script polls for
the `sessionid` cookie and exits the moment you're in. Session is stored in
`profiles/tiktok/` — **never needs to be repeated** unless you log out.

### Step 2 — upload a video
```bash
DISPLAY=:0 ./venv/bin/python upload_tiktok.py \
    /home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4 \
    /home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.txt
```
- **Arg 1** — the video (`*_portrait_*.mp4` only, else it's skipped).
- **Arg 2** *(optional)* — a `.txt` file (its contents become the caption) **or** a
  literal `"caption string"`. If omitted, no caption.
- **Arg 3** *(optional)* — a cover image. If omitted, a sibling `<video-name>.png/.jpg`
  is auto-detected and used.
- **`--force`** *(optional flag)* — upload even if the ledger says it was already posted.

The window opens **maximized on the 2nd monitor**, does video → caption → AI toggle →
cover, then **waits for you to click Post** (2-min window). Set `auto_post=True` in
[`uploader/config.py`](uploader/config.py) to click Post automatically.

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
├── config.py            Settings dataclass (auto_post, disclose_ai, portrait_glob, paths)
├── browser.py           StealthBrowser (real-Chrome context manager) + Monitor
├── ledger.py            Ledger class (SHA-256 content hash → record)
├── auth.py              LoginManager (manual login per site)
├── uploaders/
│   ├── base.py          VideoUploader — abstract template-method base
│   └── tiktok.py        TikTokUploader — TikTok Studio implementation
└── dev/
    ├── inspect_ai.py    selector-discovery tool for the AI toggle
    └── inspect_cover.py selector-discovery tool for the cover modal
login.py · upload_tiktok.py · list_uploaded.py   ← thin CLI entry points
```

| Module / class | Purpose |
|---|---|
| [`uploader/config.py`](uploader/config.py) → `Settings` | Tunable knobs (`auto_post`, `disclose_ai`, `portrait_glob`) and resolved paths (`profiles_dir`, `ledger_path`). Override per-call, e.g. `Settings(auto_post=True)`. |
| [`uploader/browser.py`](uploader/browser.py) → `StealthBrowser`, `Monitor` | `StealthBrowser` is a context manager owning the Playwright + persistent-context lifecycle (stealth real Chrome). `Monitor.pick()` reads `xrandr` and returns the 2nd monitor's geometry (falls back to 1st) so the window opens maximized there. |
| [`uploader/ledger.py`](uploader/ledger.py) → `Ledger` | Upload tracking. `is_uploaded()`, `mark_uploaded()`, `get_record()`, `list_records()`, `video_key()`. Data in `ledger.json`. |
| [`uploader/auth.py`](uploader/auth.py) → `LoginManager` | One-time manual login. Polls for the `sessionid` cookie, then exits (auto-saves into the profile). Supports `tiktok` and `instagram`. |
| [`uploader/uploaders/base.py`](uploader/uploaders/base.py) → `VideoUploader` | Abstract base. The `upload()` template method runs the rules (portrait, ledger), launches the browser, calls the per-platform steps, and records on success. Raises `UploadSkipped` / `LoginRequired`. |
| [`uploader/uploaders/tiktok.py`](uploader/uploaders/tiktok.py) → `TikTokUploader` | Concrete TikTok Studio steps (navigate, select video, caption, AI toggle, cover, post). Holds the hard-won selectors (see §7). |
| [`uploader/dev/`](uploader/dev/) | **Dev tools.** `inspect_ai` enumerates switches+state; `inspect_cover` dumps the cover-modal DOM. Rerun if TikTok changes its UI. |
| [`login.py`](login.py) · [`upload_tiktok.py`](upload_tiktok.py) · [`list_uploaded.py`](list_uploaded.py) | Thin CLI shims over the package — the documented commands. |
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
| Post success | URL contains `tiktokstudio/content`, or text like "Manage posts" / "uploaded to TikTok" | |

The 4 switches under "Show more" (in order): `High-quality uploads` (disabled),
`Disclose post content`, `AI-generated content`, `Content check lite`. The
**AI-generated content** switch is independent — you do **not** need to enable
"Disclose post content" first.

---

## 8. Ledger & rules

- **`ledger.json`** maps `sha256(file)` → `{name, path, platforms[], caption_preview,
  first_uploaded, last_uploaded}`. Created on the first confirmed post.
- Hash key means a renamed/moved file is still recognized as already-posted.
- A video is recorded **only on a confirmed post** — both manual click and `auto_post`
  are detected by `TikTokUploader._wait_for_success()`.
- `--force` bypasses the skip for intentional re-uploads.
- **Portrait rule**: `portrait_glob = "*_portrait_*.mp4"` in
  [`uploader/config.py`](uploader/config.py). Change it there if the naming convention changes.

To manually mark a video as already posted (e.g. one posted before the ledger existed):
```bash
./venv/bin/python -c "from uploader import Ledger, Settings; from pathlib import Path; \
  Ledger(Settings().ledger_path).mark_uploaded(Path('/home/alfa/pCloudDrive/target/adapter_pattern_portrait_id.mp4'), 'tiktok')"
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

1. **Decide `auto_post`** — set `auto_post=True` (default in
   [`uploader/config.py`](uploader/config.py)) for hands-off posting.
2. **`batch_upload.py`** — scan `/home/alfa/pCloudDrive/target/` for `*_portrait_*.mp4`,
   skip ledger entries, upload each with its sibling `.txt` + `.png`. (Pairs naturally
   with `auto_post=True`.) The OO API makes this a thin loop over `TikTokUploader.upload()`.
3. **Instagram Reels** — add `uploader/uploaders/instagram.py` subclassing
   `VideoUploader` (implement the 6 abstract steps); `login.py instagram` already
   creates the session/profile.
4. **Backfill ledger** — mark any videos already posted before the ledger existed.
5. **Caption trimming** — optionally strip the trailing keyword block for TikTok.

---

## 12. Quick reference

```bash
# login (once)
DISPLAY=:0 ./venv/bin/python login.py tiktok

# upload (portrait videos only; skips if already posted)
DISPLAY=:0 ./venv/bin/python upload_tiktok.py <video.mp4> [caption.txt|"text"] [cover.png] [--force]

# see uploaded history
./venv/bin/python list_uploaded.py

# free a stuck profile lock
pkill -f "profiles/tiktok"

# rediscover selectors if TikTok's UI changes
DISPLAY=:0 ./venv/bin/python -m uploader.dev.inspect_ai
DISPLAY=:0 ./venv/bin/python -m uploader.dev.inspect_cover
```

Config flags live in [`uploader/config.py`](uploader/config.py) (`Settings`):
`auto_post` (False), `disclose_ai` (True), `portrait_glob` (`*_portrait_*.mp4`).
