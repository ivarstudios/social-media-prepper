#!/usr/bin/env bash
# IVAR SMP installer for macOS and Linux. Options: --yes  --claude-only
exec bash "$(dirname "${BASH_SOURCE[0]}")/installer/install.sh" "$@"
