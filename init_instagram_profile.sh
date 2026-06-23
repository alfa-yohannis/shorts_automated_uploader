#!/usr/bin/env bash
# Initialize the Instagram profile (one-time): COPY your already-logged-in Instagram
# session from a real Google Chrome profile into profiles/instagram/, then open a
# Chrome window to VERIFY it and flush it to disk. See README §13.
#
# Why copy instead of logging in here: Instagram captcha-walls fresh logins inside
# an automated/CDP Chrome — BOTH "Log in with Facebook" AND direct username/password
# bounce back to the login page. The only reliable session is one created in your
# NORMAL Chrome, so log into instagram.com there first, then run this.
#
# Chrome MUST be fully closed during the copy (an open source profile is locked).
# The verify window is launched DETACHED (setsid) so it survives this script
# exiting; on success the script closes it cleanly to flush the session to disk.
#
#   ./init_instagram_profile.sh                 # copy from Chrome "Default" + verify
#   ./init_instagram_profile.sh "Profile 3"     # copy from a named profile
#   ./init_instagram_profile.sh --no-launch     # copy only, skip the verify window
#
set -euo pipefail
cd "$(dirname "$0")"

CHROME_DIR="$HOME/.config/google-chrome"
DEST="profiles/instagram"
CDP_PORT="${CDP_PORT:-9222}"
DISPLAY="${DISPLAY:-:0}"; export DISPLAY

# --- args: a profile name and/or --no-launch (in any order) ---
SRC_PROFILE="Default"
LAUNCH=1
for a in "$@"; do
    case "$a" in
        --no-launch) LAUNCH=0 ;;
        *) SRC_PROFILE="$a" ;;
    esac
done

chrome_bin() { command -v google-chrome || command -v google-chrome-stable || command -v chromium || true; }

# Open the seeded profile in a DETACHED real Chrome (survives this script exiting),
# with the DevTools port, on instagram.com — to verify the copied session.
launch_window() {
    local chrome profile pid i
    chrome="$(chrome_bin)"
    [ -n "$chrome" ] || { echo "==> google-chrome not found on PATH; open the profile by hand." >&2; return 1; }
    profile="$PWD/$DEST"
    # free the port if a previous window is still up (avoid a profile/port collision)
    if command -v lsof >/dev/null; then
        pid="$(lsof -ti "tcp:$CDP_PORT" 2>/dev/null | head -1 || true)"
        [ -n "$pid" ] && { kill "$pid" 2>/dev/null || true; sleep 2; }
    fi
    echo "==> Opening Chrome on the profile (detached — it will STAY open)…"
    setsid nohup "$chrome" \
        --user-data-dir="$profile" \
        --remote-debugging-port="$CDP_PORT" \
        --remote-debugging-address=127.0.0.1 \
        --remote-allow-origins='*' \
        --no-first-run --no-default-browser-check --disable-infobars \
        "https://www.instagram.com/" \
        >/dev/null 2>&1 &
    disown
    for i in $(seq 1 25); do
        curl -s --max-time 2 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 && return 0
        sleep 1
    done
    echo "==> Window launched but DevTools port $CDP_PORT didn't answer in time." >&2
    return 0
}

# Verify (read-only over CDP) that the COPIED Instagram session is logged in. The
# login comes from the seeded profile — Instagram captcha-walls fresh logins inside
# this automated window — so this just confirms the copy worked. Never closes the
# browser/tabs; only attaches and inspects.
wait_for_login() {
    ./venv/bin/python - "$CDP_PORT" <<'PY'
import sys, time
from playwright.sync_api import sync_playwright
port = sys.argv[1]
deadline = time.time() + 75       # verifying the copied session, not a manual-login wait
pw = sync_playwright().start()
try:
    try:
        b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    except Exception:
        print("    (couldn't attach to the verification window.)")
        sys.exit(3)
    ctx = b.contexts[0]
    while time.time() < deadline:
        for pg in list(ctx.pages):
            try:
                if "instagram.com" not in pg.url:
                    continue
                if pg.locator('svg[aria-label="New post"]').count() or \
                   pg.locator('svg[aria-label="Home"]').count():
                    print("    ✓ Instagram session is logged in.")
                    sys.exit(0)
            except Exception:
                pass
        time.sleep(4)
    print("    (copied profile is NOT logged in — see the instructions above.)")
    sys.exit(1)
finally:
    pw.stop()    # detach only; the window stays open
PY
}

# Close the window CLEANLY (SIGTERM) so Chrome flushes cookies/session to disk —
# that's what persists the login into profiles/instagram. kill -9 would skip the
# flush and risk losing the just-made session.
close_and_save() {
    local pid i
    command -v lsof >/dev/null && pid="$(lsof -ti "tcp:$CDP_PORT" 2>/dev/null | head -1 || true)"
    if [ -z "${pid:-}" ]; then
        for p in $(pgrep -x chrome 2>/dev/null); do
            tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q "user-data-dir=$PWD/$DEST" && { pid="$p"; break; }
        done
    fi
    [ -z "${pid:-}" ] && { echo "    (window already closed — session was saved on login.)"; return 0; }
    echo "==> Saving session to $DEST (closing Chrome cleanly)…"
    kill "$pid" 2>/dev/null || true
    for i in $(seq 1 15); do
        kill -0 "$pid" 2>/dev/null || { echo "    ✓ Session saved to $DEST."; return 0; }
        sleep 1
    done
    echo "    (Chrome is still shutting down; the session will flush shortly.)"
}

if [ ! -x ./venv/bin/python ]; then
    echo "==> venv not found. Run ./setup.sh first." >&2
    exit 1
fi
command -v rsync >/dev/null || { echo "==> rsync missing: sudo apt install rsync" >&2; exit 1; }

# --- decide whether to (re)seed ---
DO_SEED=1
if [ -d "$DEST" ]; then
    echo "==> $DEST already exists."
    read -r -p "    Re-seed it from Chrome '$SRC_PROFILE' (overwrites)? [y/N] " ans
    case "$ans" in [yY]*) DO_SEED=1 ;; *) DO_SEED=0; echo "    Keeping existing profile." ;; esac
fi

if [ "$DO_SEED" = 1 ]; then
    # Chrome must be closed so the source profile isn't locked mid-copy.
    if pgrep -af "/opt/google/chrome/chrome" | grep -vqE "crashpad|--type="; then
        echo "==> Google Chrome is RUNNING — it must be closed to copy the session." >&2
        echo "    1) In Chrome (profile '$SRC_PROFILE'), open instagram.com and confirm" >&2
        echo "       you're logged in (you see your feed)." >&2
        echo "    2) FULLY quit Chrome (all windows)." >&2
        echo "    3) Re-run this script." >&2
        exit 1
    fi
    # source profile sanity
    if [ ! -d "$CHROME_DIR/$SRC_PROFILE" ]; then
        echo "==> Source profile not found: $CHROME_DIR/$SRC_PROFILE" >&2
        echo "    Available profiles:" >&2
        ./venv/bin/python - <<'PY' >&2
import json, os
p = os.path.expanduser("~/.config/google-chrome/Local State")
for k, v in json.load(open(p))["profile"]["info_cache"].items():
    print(f"      {k}  → {v.get('name')!r}  {v.get('user_name')!r}")
PY
        exit 1
    fi
    echo "==> Seeding $DEST from Chrome profile '$SRC_PROFILE' …"
    rm -rf "$DEST"
    mkdir -p "$DEST/Default"
    cp "$CHROME_DIR/Local State" "$DEST/Local State"
    rsync -a \
      --exclude Cache --exclude 'Code Cache' --exclude GPUCache --exclude DawnCache \
      --exclude GraphiteDawnCache --exclude 'Service Worker/CacheStorage' \
      --exclude component_crx_cache --exclude extensions_crx_cache --exclude Crashpad \
      "$CHROME_DIR/$SRC_PROFILE/" "$DEST/Default/"
    echo "==> Done. profiles/instagram/ seeded ($(du -sh "$DEST" | cut -f1))."
fi

if [ "$LAUNCH" = 0 ]; then
    echo "==> --no-launch: not opening a window. Run me again without it to log in."
    exit 0
fi

launch_window

cat <<EOF

==> A Chrome window is open on the Instagram profile to VERIFY the copied session.
    • If it shows your Instagram FEED — the session copied fine; you're done.
    • If it shows a LOGIN page — your source Chrome profile ('$SRC_PROFILE') wasn't
      logged into Instagram. Do NOT try to log in here: Instagram captcha-walls fresh
      logins inside this automated window. Instead:
          1) open your NORMAL Chrome and log into instagram.com there,
          2) fully close Chrome,
          3) re-run:  ./init_instagram_profile.sh

    Do NOT run ./batch_upload.sh while this window is open — its cleanup kills Chrome.
EOF

echo
echo "==> Verifying the copied Instagram session…"
if wait_for_login; then
    close_and_save
    echo
    echo "==> profiles/instagram is ready (logged in, saved). Upload with:"
    echo "      DISPLAY=$DISPLAY ./venv/bin/python upload_instagram.py <video.mp4> [caption.txt] --chrome --post"
    echo "    or the batch:  ./batch_upload.sh --limit 1 --platforms instagram"
else
    echo "==> The copied profile is NOT logged in. Log into Instagram in your NORMAL"
    echo "    Chrome, fully close it, then re-run this script (steps above)."
    exit 1
fi
