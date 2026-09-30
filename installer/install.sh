#!/usr/bin/env bash
# IVAR SMP installer for macOS and Linux. Run ./install.sh (start.sh runs it on first use). Safe to re-run.
# It asks where the programs (uv, Python), the vision models and SMP's data go, keeps the answers in locations.json
# in the app folder, and moves what's already there when a folder changes. ExifTool and Ollama come from Homebrew
# or the system, which keep them in their own folders.
# Options: --yes (no questions)  --claude-only (no local model; use the Claude API)
#          --tools-dir DIR  --models-dir DIR  --data-dir DIR (the folders, without asking)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCATIONS="$REPO/locations.json"
DEFAULT_TOOLS="$REPO/tools"
DEFAULT_DATA="$HOME/.local/share/IVAR-SMP"
UV_VERSION="0.12.18"
PYTHON_VERSION="3.12"
YES=0
CLAUDE_ONLY=0
ARG_tools=""; ARG_models=""; ARG_data=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --claude-only) CLAUDE_ONLY=1 ;;
    --tools-dir=*) ARG_tools="${1#*=}" ;;
    --models-dir=*) ARG_models="${1#*=}" ;;
    --data-dir=*) ARG_data="${1#*=}" ;;
    --tools-dir|--models-dir|--data-dir)
      [ $# -gt 1 ] || { echo "$1 needs a folder" >&2; exit 1; }
      k="${1#--}"; printf -v "ARG_${k%-dir}" '%s' "$2"; shift ;;
  esac
  shift
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    \033[33mWARNING: %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$1"; exit 1; }
ask() {  # ask "question" default(y/n)
  if [ "$YES" = 1 ]; then [ "$2" = y ]; return; fi
  read -r -p "$1 [$( [ "$2" = y ] && echo Y/n || echo y/N )] " a || true
  a="${a:-$2}"; [[ "$a" =~ ^[Yy] ]]
}

# ---- folders ----------------------------------------------------------------------------------------------------
# OLD_x: where folder x is now, NEW_x: where it goes, NOW_x: where it is while moving (x: tools, models, data)
old_of() { local n="OLD_$1"; printf '%s' "${!n:-}"; }
new_of() { local n="NEW_$1"; printf '%s' "${!n:-}"; }
label_of() { case "$1" in tools) echo Programs ;; models) echo Models ;; data) echo Data ;; esac; }
what_of() { case "$1" in tools) echo "the programs" ;; models) echo "the vision models" ;; data) echo "SMP's settings and cache" ;; esac; }
ifnot_of() {
  case "$1" in
    tools) echo "they're downloaded again" ;;
    models) echo "download the model again from Setup in the app" ;;
    data) echo "SMP starts with fresh settings" ;;
  esac
}

saved() {  # saved KEY: that folder as locations.json has it, or nothing
  [ -f "$LOCATIONS" ] || return 0
  sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$LOCATIONS" | head -n 1 | sed 's/\\\//\//g'
}

inside() { case "$1/" in "$2/"*) return 0 ;; esac; return 1; }   # inside PATH FOLDER: PATH is FOLDER or in it
has_files() { [ -d "$1" ] && [ -n "$(ls -A "$1" 2>/dev/null)" ]; }
size_of() { du -sh "$1" 2>/dev/null | cut -f1; }
free_of() {  # free_of PATH: free space on its disk
  local p="$1"
  while [ ! -d "$p" ]; do p="$(dirname "$p")"; done
  df -h "$p" 2>/dev/null | awk 'NR == 2 { print $4 }'
}

normalize() {  # normalize TEXT: a typed folder as an absolute path, or nothing
  local t="$1"
  t="${t#"${t%%[![:space:]]*}"}"; t="${t%"${t##*[![:space:]]}"}"
  t="${t#\"}"; t="${t%\"}"; t="${t#\'}"; t="${t%\'}"
  case "$t" in "~") t="$HOME" ;; "~/"*) t="$HOME/${t#\~/}" ;; esac
  case "$t" in /*) ;; *) return 0 ;; esac
  while [ "$t" != "/" ] && [ "${t%/}" != "$t" ]; do t="${t%/}"; done
  printf '%s' "$t"
}

problem() {  # problem KEY PATH: why PATH can't be that folder, or nothing
  local key="$1" path="$2" other old
  if [ -z "$path" ]; then echo "Type a full path, for example $HOME/IVAR-SMP/$key."; return 0; fi
  if [ "$path" = "/" ]; then echo "Pick a folder, not the whole disk."; return 0; fi
  case "$path" in *'"'*|*'\'*) echo "Pick a folder without quotes or backslashes in its name."; return 0 ;; esac
  if [ "$path" = "$REPO" ]; then echo "Pick a folder of its own, not the app folder."; return 0; fi
  for other in tools models data; do
    if [ "$other" != "$key" ] && [ "$(new_of "$other")" = "$path" ]; then
      echo "That's already the $other folder: pick another one."; return 0
    fi
  done
  old="$(old_of "$key")"
  if [ "$path" != "$old" ] && inside "$path" "$old" && has_files "$old"; then
    echo "It can't go inside the folder it's moving out of ($old)."; return 0
  fi
  { mkdir -p "$path" && touch "$path/.smp-write-test" && rm -f "$path/.smp-write-test"; } 2>/dev/null ||
    echo "SMP can't write there."
  return 0
}

choose() {  # choose KEY GIVEN CURRENT ABOUT: sets CHOSEN
  local key="$1" given="$2" current="$3" about="$4" path p a facts=""
  if [ -n "$given" ] || [ "$YES" = 1 ]; then
    path="$current"
    if [ -n "$given" ]; then path="$(normalize "$given")"; fi
    p="$(problem "$key" "$path")"
    [ -z "$p" ] || fail "$(label_of "$key") folder '${given:-$current}': $p"
    info "$(printf '%-9s %s' "$(label_of "$key"):" "$path")"
    CHOSEN="$path"; return 0
  fi
  echo
  info "$about"
  if has_files "$current"; then facts="holds $(size_of "$current"), "; fi
  printf '      \033[1m%s\033[0m   (%s%s free)\n' "$current" "$facts" "$(free_of "$current")"
  while true; do
    read -r -p "      Press Enter to keep it, or type another folder: " a || fail "No answer: run with --yes to keep the folders."
    path="$current"
    if [ -n "$a" ]; then path="$(normalize "$a")"; fi
    p="$(problem "$key" "$path")"
    if [ -z "$p" ]; then CHOSEN="$path"; return 0; fi
    printf '      \033[33m%s\033[0m\n' "$p"
  done
}

save_locations() {  # save_locations TOOLS MODELS DATA: only the folders that aren't the default
  local body="" sep=""
  if [ "$1" != "$DEFAULT_TOOLS" ]; then body="$body$sep  \"tools\": \"$1\""; sep=$',\n'; fi
  if [ "$2" != "$3/ollama-models" ]; then body="$body$sep  \"models\": \"$2\""; sep=$',\n'; fi
  if [ "$3" != "$DEFAULT_DATA" ]; then body="$body$sep  \"data\": \"$3\""; fi
  if [ -n "$body" ]; then printf '{\n%s\n}\n' "$body" > "$LOCATIONS"; else rm -f "$LOCATIONS"; fi
}

move_folder() {  # move_folder FROM TO KEEP...: everything in FROM into TO, except KEEP folders inside FROM
  local from="$1" to="$2" entry k skip
  shift 2
  mkdir -p "$to" || return 1
  for entry in "$from"/* "$from"/.[!.]* "$from"/..?*; do
    [ -e "$entry" ] || continue
    skip=0
    for k in "$@"; do
      if [ -n "$k" ] && [ -e "$k" ] && inside "$k" "$entry"; then skip=1; fi
    done
    if [ "$skip" = 1 ]; then continue; fi
    if [ -e "$to/$(basename "$entry")" ]; then
      cp -a "$entry" "$to/" && rm -rf "$entry" || return 1
    else
      mv "$entry" "$to/" || return 1
    fi
  done
  rmdir "$from" 2>/dev/null || true
}

smp_running() { pgrep -f -- '-m smp( |$)' >/dev/null 2>&1; }

stop_own_ollama() {  # SMP's own Ollama listens on port 11436 and keeps the models open
  local pids
  pids="$(lsof -ti tcp:11436 -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    info "Stopped SMP's Ollama (the app starts it again when needed)"
    sleep 1
  fi
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

step "Choosing folders"
OLD_tools="$(saved tools)"; OLD_tools="${OLD_tools:-$DEFAULT_TOOLS}"
OLD_data="$(saved data)"; OLD_data="${OLD_data:-$DEFAULT_DATA}"
SAVED_models="$(saved models)"
OLD_models="${SAVED_models:-$OLD_data/ollama-models}"
NEW_tools=""; NEW_models=""; NEW_data=""
info "The app and its Python environment (.venv) stay in $REPO"
[ "$YES" = 1 ] || info "For each folder, press Enter to keep it or type another one."
choose tools "$ARG_tools" "$OLD_tools" \
  "Programs: uv and Python (about 150 MB; ExifTool and Ollama come from Homebrew or the system)"
NEW_tools="$CHOSEN"
choose data "$ARG_data" "$OLD_data" \
  "Data: settings, answer cache, thumbnails, place names and the undo record (grows as SMP is used)"
NEW_data="$CHOSEN"
models_now="${SAVED_models:-$NEW_data/ollama-models}"   # by default the models live in the data folder
if [ "$CLAUDE_ONLY" = 1 ] && [ -z "$ARG_models" ]; then
  NEW_models="$models_now"
else
  choose models "$ARG_models" "$models_now" "Models: the vision model, 6 to 36 GB, downloaded from Setup in the app"
  NEW_models="$CHOSEN"
fi

MOVES=""
for k in models tools data; do
  if [ "$(old_of $k)" != "$(new_of $k)" ] && has_files "$(old_of $k)"; then MOVES="$MOVES $k"; fi
done
if [ -n "$MOVES" ] && [ ! -x "$REPO/.venv/bin/python" ] && [ ! -f "$LOCATIONS" ]; then
  # a first install: the default folders may belong to another copy of SMP on this computer, which still uses them
  for k in $MOVES; do info "Left $(old_of $k) as it is: it may belong to another copy of SMP"; done
  MOVES=""
fi
VENV_HOME="$(sed -n 's/^home *= *//p' "$REPO/.venv/pyvenv.cfg" 2>/dev/null || true)"
VENV_STALE=0
if [ -x "$REPO/.venv/bin/python" ] && ! inside "$VENV_HOME" "$NEW_tools/python"; then VENV_STALE=1; fi
if { [ -n "$MOVES" ] || [ "$VENV_STALE" = 1 ]; } && smp_running; then
  fail "IVAR SMP is running. Stop it (close its terminal window), then run this again."
fi

NOW_tools="$OLD_tools"; NOW_models="$OLD_models"; NOW_data="$OLD_data"
for k in $MOVES; do
  from="$(old_of $k)"; to="$(new_of $k)"
  echo
  if ! ask "    Move $(what_of $k) ($(size_of "$from")) from $from to $to? If not, $(ifnot_of $k)." y; then
    info "Left in $from"
    continue
  fi
  [ "$k" = data ] || stop_own_ollama
  info "Moving $(what_of $k) to $to (large folders can take a few minutes)..."
  move_folder "$from" "$to" "$REPO" "$OLD_tools" "$NEW_tools" "$OLD_models" "$NEW_models" "$OLD_data" "$NEW_data" ||
    fail "Moving $(what_of $k) stopped. Close anything that uses them and run this again to move the rest."
  printf -v "NOW_$k" '%s' "$to"
  save_locations "$NOW_tools" "$NOW_models" "$NOW_data"   # a later failure mustn't lose track of what moved
done
save_locations "$NEW_tools" "$NEW_models" "$NEW_data"
TOOLS="$NEW_tools"

step "Installing uv (Python package manager)"
UV="$TOOLS/uv/uv"
if [ ! -x "$UV" ] || ! "$UV" --version | grep -q "^uv $UV_VERSION"; then
  mkdir -p "$TOOLS/uv"
  # into this folder only: no install receipt (it would take over the user's own `uv self update`), no PATH change
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" |
    env UV_INSTALL_DIR="$TOOLS/uv" UV_UNMANAGED_INSTALL="$TOOLS/uv" sh
fi
info "$("$UV" --version)"

step "Installing Python $PYTHON_VERSION and IVAR SMP"
# Python, its downloads and the package cache go into the programs folder, not the home folder
export UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_CACHE_DIR="$TOOLS/uv-cache" UV_MANAGED_PYTHON=1 UV_LINK_MODE=copy
"$UV" python install "$PYTHON_VERSION" --no-bin
if [ "$VENV_STALE" = 1 ] || [ ! -x "$REPO/.venv/bin/python" ]; then
  "$UV" venv "$REPO/.venv" --python "$PYTHON_VERSION" --clear
fi
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
echo "where you download the vision model for this computer or add a Claude API key. To move a folder later, run"
echo "./install.sh again."
