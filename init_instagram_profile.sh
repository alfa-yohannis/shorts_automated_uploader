#!/usr/bin/env bash
# Initialize the Instagram profile (one-time) by seeding profiles/instagram/ from
# an established, logged-in Google Chrome profile, then opening it over CDP so you
# can log into Instagram once (see README §13).
#
# Instagram can't reuse a Playwright profile on Linux/KDE (keyring-encrypted "v11"
# cookies + captcha walls), so we copy a real, history-rich Chrome profile and
# drive THAT over CDP. Chrome MUST be closed during the copy.
#
#   ./init_instagram_profile.sh                 # seeds from Chrome "Default"
#   ./init_instagram_profile.sh "Profile 3"     # seeds from a named profile
#
set -euo pipefail
cd "$(dirname "$0")"

SRC_PROFILE="${1:-Default}"
CHROME_DIR="$HOME/.config/google-chrome"
DEST="profiles/instagram"

if [ ! -x ./venv/bin/python ]; then
    echo "==> venv not found. Run ./setup.sh first." >&2
    exit 1
fi
command -v rsync >/dev/null || { echo "==> rsync missing: sudo apt install rsync" >&2; exit 1; }

# --- Chrome must be closed (open Chrome locks the profile, corrupting the copy) ---
if pgrep -f "/opt/google/chrome/chrome" | grep -qv crashpad 2>/dev/null \
   && pgrep -af "/opt/google/chrome/chrome" | grep -vqE "crashpad|--type="; then
    echo "==> Google Chrome appears to be RUNNING. Close it completely first" >&2
    echo "    (the copy needs an unlocked profile), then re-run this script." >&2
    exit 1
fi

# --- source profile sanity ---
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

# --- guard an existing seed ---
if [ -d "$DEST" ]; then
    echo "==> $DEST already exists."
    read -r -p "    Overwrite it? [y/N] " ans
    case "$ans" in [yY]*) rm -rf "$DEST" ;; *) echo "    Kept existing. Exiting."; exit 0 ;; esac
fi

echo "==> Seeding $DEST from Chrome profile '$SRC_PROFILE' ..."
mkdir -p "$DEST/Default"
cp "$CHROME_DIR/Local State" "$DEST/Local State"
rsync -a \
  --exclude Cache --exclude 'Code Cache' --exclude GPUCache --exclude DawnCache \
  --exclude GraphiteDawnCache --exclude 'Service Worker/CacheStorage' \
  --exclude component_crx_cache --exclude extensions_crx_cache --exclude Crashpad \
  "$CHROME_DIR/$SRC_PROFILE/" "$DEST/Default/"

echo
echo "==> Done. profiles/instagram/ seeded ($(du -sh "$DEST" | cut -f1))."
echo "    Now open it and log into Instagram once:"
echo
echo "      DISPLAY=${DISPLAY:-:0} ./venv/bin/python upload_instagram.py \\"
echo "        /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.mp4 \\"
echo "        /home/alfa/pCloudDrive/target/bridge_pattern_portrait_id.txt --chrome"
echo
echo "    If the window opens logged-out, just log into Instagram in it once"
echo "    (\"Log in with Facebook\" tends to clear the captcha) — it persists after."
