#!/usr/bin/env bash
# Initialize the TikTok login profile (one-time, interactive).
# Opens a real Google Chrome at TikTok's login page; you log in by hand
# (password/2FA/captcha all fine). The script polls for the 'sessionid' cookie
# and exits the moment you're in, saving the session to profiles/tiktok/.
# Re-run only if you log out. Honors MONITOR (1-based screen) and DISPLAY.
#
#   ./init_tiktok_profile.sh                 # uses DISPLAY=:0
#   DISPLAY=:1 MONITOR=1 ./init_tiktok_profile.sh
#
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ./venv/bin/python ]; then
    echo "==> venv not found. Run ./setup.sh first." >&2
    exit 1
fi

export DISPLAY="${DISPLAY:-:0}"

if [ -d profiles/tiktok ]; then
    echo "==> profiles/tiktok already exists."
    read -r -p "    Re-run login anyway? [y/N] " ans
    case "$ans" in
        [yY]*) ;;
        *) echo "    Skipped."; exit 0 ;;
    esac
fi

echo "==> Opening Chrome on DISPLAY=$DISPLAY (MONITOR=${MONITOR:-default})."
echo "    Log in by hand; this exits automatically once you're in."
exec ./venv/bin/python login.py tiktok
