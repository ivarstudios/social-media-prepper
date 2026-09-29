#!/usr/bin/env bash
# IVAR SMP installer for macOS and Linux. Run ./install.sh (start.sh runs it on first use). Safe to re-run.
# Options: --yes (no questions)  --claude-only (no local model; use the Claude API)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$REPO/tools"
UV_VERSION="0.12.18"
PYTHON_VERSION="3.12"
YES=0
CLAUDE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --claude-only) CLAUDE_ONLY=1 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    \033[33mWARNING: %s\033[0m\n' "$1"; }
ask() {  # ask "question" default(y/n)
  if [ "$YES" = 1 ]; then [ "$2" = y ]; return; fi
  read -r -p "$1 [$( [ "$2" = y ] && echo Y/n || echo y/N )] " a || true
  a="${a:-$2}"; [[ "$a" =~ ^[Yy] ]]
}

echo "IVAR SMP (Social Media Prepper) installer"
echo "Made by IVAR Studios. Folder: $REPO"
OS="$(uname -s)"
HAS_BREW=0; command -v brew >/dev/null 2>&1 && HAS_BREW=1

step "Checking this computer"
info "$OS $(uname -m)"
if [ "$OS" = Linux ] && ! command -v nvidia-smi >/dev/null 2>&1 && [ "$CLAUDE_ONLY" = 0 ]; then
  info "No NVIDIA GPU found: the local vision model would be very slow. The Claude API works well instead."
  ask "Set up the local model runtime (Ollama) anyway?" n || CLAUDE_ONLY=1
fi

step "Installing uv (Python package manager)"
UV="$TOOLS/uv/uv"
if [ ! -x "$UV" ] || ! "$UV" --version | grep -q "^uv $UV_VERSION"; then
  mkdir -p "$TOOLS/uv"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR="$TOOLS/uv" UV_NO_MODIFY_PATH=1 sh
fi
info "$("$UV" --version)"

step "Installing Python $PYTHON_VERSION and IVAR SMP"
"$UV" python install "$PYTHON_VERSION"
[ -x "$REPO/.venv/bin/python" ] || "$UV" venv "$REPO/.venv" --python "$PYTHON_VERSION"
(cd "$REPO" && "$UV" pip install --python "$REPO/.venv/bin/python" -e .)

step "ExifTool"
if command -v exiftool >/dev/null 2>&1; then
  info "ExifTool $(exiftool -ver) ($(command -v exiftool))"
elif [ "$OS" = Darwin ] && [ "$HAS_BREW" = 1 ]; then
  brew install exiftool
else
  warn "ExifTool is missing. Install it, then run this installer again:"
  if [ "$OS" = Darwin ]; then info "  install Homebrew (https://brew.sh), then: brew install exiftool"
  else info "  sudo apt install libimage-exiftool-perl   (Debian/Ubuntu)  or  sudo dnf install perl-Image-ExifTool"; fi
fi

if [ "$CLAUDE_ONLY" = 1 ]; then
  step "Skipping Ollama: this computer uses the Claude API"
else
  step "Ollama (runs the vision model on this computer)"
  if command -v ollama >/dev/null 2>&1 || [ -x /Applications/Ollama.app/Contents/Resources/ollama ]; then
    info "Ollama found"
  elif [ "$OS" = Darwin ] && [ "$HAS_BREW" = 1 ]; then
    brew install ollama
  elif [ "$OS" = Darwin ]; then
    warn "Ollama is missing: download it from https://ollama.com/download, or use the Claude API."
  else
    warn "Ollama is missing. Install it with: curl -fsSL https://ollama.com/install.sh | sh"
    info "  (it asks for your password), or use the Claude API."
  fi
fi

step "Health check"
"$REPO/.venv/bin/python" -m smp doctor || warn "Some checks failed (see above)."
echo
echo "Start IVAR SMP with ./start.sh (on a Mac you can double-click start.command). The first start shows Setup,"
echo "where you download the vision model for this computer or add a Claude API key."
