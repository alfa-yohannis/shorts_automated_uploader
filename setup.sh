#!/usr/bin/env bash
# Fresh-clone setup for shorts_automated_uploader.
# Creates the venv and installs pinned deps. We drive the system Google Chrome
# (channel="chrome"), so no Playwright browser binary is downloaded.
# The venv/, profiles/, sessions/ and ledger.json are gitignored, so a fresh clone
# has none of them — this script (re)builds the runtime bits.
#
#   ./setup.sh
#
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "==> Using interpreter: $($PYTHON --version 2>&1) ($(command -v "$PYTHON"))"

# 1. venv
if [ ! -d venv ]; then
    echo "==> Creating venv/"
    "$PYTHON" -m venv venv
else
    echo "==> venv/ already exists, reusing"
fi

# 2. python deps
echo "==> Installing requirements"
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. runtime dirs that are gitignored
mkdir -p profiles sessions

echo
echo "==> Done."
echo "    This drives your system Google Chrome (no chromium download)."
echo "    Check you have it + an X display:"
echo "      google-chrome --version"
echo "      echo \$DISPLAY        # we use :0"
echo
echo "    Then log in once:"
echo "      DISPLAY=:0 ./venv/bin/python login.py tiktok"
