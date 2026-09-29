# Packaging: a Windows installer and IVAR SMP.exe

**Status:** idea, not started. Today SMP starts from `start.bat`, which installs everything into its own folder
on first run (see the README).

## Goal

Users download `IVAR-SMP-Setup.exe`, click through a normal installer, and start **IVAR SMP** from the
Start menu like any other app: its own window, an entry in *Settings → Apps* with an uninstaller, and no Python,
console window or `.bat` in sight.

## Plan

### 1. The app as an .exe
- **PyInstaller**, one-folder build: Python, SMP and its libraries in `IVAR SMP\`, started by `IVAR SMP.exe`
  (about 60–80 MB with ExifTool bundled).
- **Its own window** instead of a browser tab: **pywebview**, which shows the same web UI in a window using the
  Edge WebView2 engine built into Windows 11.
- **Folder dialog** from pywebview (`create_file_dialog(FOLDER_DIALOG)`). The current picker starts
  `sys.executable -c ...`, which doesn't work in a frozen app, where `sys.executable` is the app itself.
- Code changes: locate bundled files through `sys._MEIPASS` (static files, the ExifTool config, ExifTool itself),
  allow a single running instance (a second start focuses the open window), and log to a file in the data folder
  since there's no console.

### 2. The installer
- **Inno Setup** (free): `IVAR-SMP-Setup.exe`.
- Per-user install into `%LOCALAPPDATA%\Programs\IVAR SMP`, so no admin rights are needed.
- Start menu and optional desktop shortcut with `smp-icon.ico`, and a normal uninstaller.
- The uninstaller leaves `%LOCALAPPDATA%\IVAR-SMP` (settings, downloaded models) unless the user ticks
  "also remove downloaded models and settings".

### 3. Ollama and the model stay out of the installer
Ollama is 1–2 GB and only useful with a suitable GPU, so it isn't bundled. The in-app **Setup** panel gets a
*Download Ollama* step next to *Download model*: the same pinned version and SHA-256 check as `install.ps1`,
installed into the data folder. Claude-only users never download it.

### 4. Signing
- **Unsigned** (fine for a beta): Windows SmartScreen shows "Windows protected your PC" on first run;
  users click *More info → Run anyway*. Some antivirus products flag PyInstaller builds now and then.
- **Signed**: *Azure Trusted Signing* (about $10/month, needs a verified company identity) or an OV
  code-signing certificate (a few hundred dollars a year). Removes the warnings. Worth it once SMP goes beyond a
  handful of users.

### 5. Build and release
- `installer/build.ps1`: `uv` environment → PyInstaller → Inno Setup's `ISCC.exe` → `dist/IVAR-SMP-Setup-<version>.exe`.
- Later: a GitHub Actions job on a Windows runner that builds and attaches the installer to each GitHub Release.
- Optional: on start, check the latest release and offer the update.

### 6. Testing
**Windows Sandbox** (included in Windows 11 Pro): a throwaway clean Windows, to install exactly as a first-time
user would, including the SmartScreen prompt and the Setup panel's downloads.

## Not now: Mac

The same approach gives a `.app` in a `.dmg` (PyInstaller or py2app, pywebview uses WKWebView). Without an Apple
Developer account ($99/year) for signing and notarisation, macOS blocks it as coming from an unidentified
developer. `start.command` covers Mac users until one actually needs an app.

## Keep

`start.bat`, `install.bat` and `update.bat` stay as the developer route (run from a git clone).
