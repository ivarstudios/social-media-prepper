#!/usr/bin/env bash
# IVAR SMP for macOS and Linux: installs on first run, then starts and opens the browser.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -x .venv/bin/python ]; then
  echo "IVAR SMP isn't installed yet: running the installer first."
  bash installer/install.sh --yes
fi
exec .venv/bin/python -m smp "$@"
