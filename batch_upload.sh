#!/usr/bin/env bash
# Cron-friendly wrapper around batch_upload.py.
# Sets up the GUI environment (DISPLAY/XAUTHORITY — cron has neither), cd's into
# the repo, runs the venv Python, and appends a timestamped log. Any extra args
# are passed straight through to batch_upload.py.
#
#   ./batch_upload.sh                  # 1 pattern (en+id) to TikTok + Instagram, auto-post
#   ./batch_upload.sh --limit 3        # override per-run count
#   ./batch_upload.sh --dry-run        # see what would upload
#
# Crontab (run at 05:00, 11:00, 17:00 daily) — edit with `crontab -e`:
#   0 5,11,17 * * * /home/alfa/projects/shorts_automated_uploader/batch_upload.sh >> /home/alfa/projects/shorts_automated_uploader/logs/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")"

# --- GUI env (cron starts with an empty environment) ---
export DISPLAY="${DISPLAY:-:0}"
# Chrome needs the X authority cookie to draw on :0; point at the user's file.
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
# Which monitor the TikTok window opens on (1-based); see uploader/browser.py.
export MONITOR="${MONITOR:-1}"

# --- keyring access for Instagram's keyring-encrypted (v11) cookies ---
# Instagram's session cookies are encrypted with the OS keyring; Chrome decrypts
# them through the secret-service over the *session* D-Bus. Cron starts without a
# D-Bus session, so a scheduled Chrome can't reach the keyring and lands LOGGED
# OUT (TikTok is unaffected — Playwright forces a portable cookie store). Point at
# the user's running session bus so cron-launched Chrome reaches the (already
# unlocked, because you're logged into the desktop) keyring like an interactive run.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

mkdir -p logs
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "================ $STAMP  batch_upload.sh $* ================"

if [ ! -x ./venv/bin/python ]; then
    echo "venv missing — run ./setup.sh first." >&2
    exit 1
fi

# Single-instance guard: don't let an 11:00 run start if 05:00 is somehow still going.
LOCK="/tmp/shorts_batch_upload.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "Another batch_upload run is in progress (lock held) — skipping this trigger." >&2
    exit 0
fi

exec ./venv/bin/python batch_upload.py "$@"
