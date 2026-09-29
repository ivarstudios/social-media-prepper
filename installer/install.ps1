<#
  IVAR SMP installer for Windows 10/11 (PowerShell 5.1+). Run via install.bat (start.bat runs it on first use).
  Safe to re-run: it repairs and updates. No admin rights needed. Everything goes into this folder (tools\, .venv\)
  and the models into %LOCALAPPDATA%\IVAR-SMP.

  Options (pass to install.bat):
    -Yes          accept all defaults, no questions
    -ClaudeOnly   don't install Ollama: use the Claude API only (no local model)
    -NoShortcuts  don't create desktop and Start menu shortcuts
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$ClaudeOnly,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Repo "tools"
$LogFile = Join-Path $Repo "install.log"

# ---- pinned versions (the tested builds) ---------------------------------------------------------------------------
$UvVersion = "0.12.18"
$PythonVersion = "3.12"
$ExifToolVersion = "13.59"
$ExifToolSha256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"
$OllamaVersion = "0.34.4"
$OllamaUrl = "https://github.com/ollama/ollama/releases/download/v$OllamaVersion/ollama-windows-amd64.zip"
$OllamaSha256 = "535193f38f3344e5b08f5d1c171c31ce11aa17f0124ff69ae26d8ec7fe06fa62"

$script:Warnings = New-Object System.Collections.ArrayList

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    for ($i = 0; $i -lt 5; $i++) {
        try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction Stop; return } catch { Start-Sleep -Milliseconds 200 }
    }
}
function Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan; Log "STEP $msg" }
function Info([string]$msg) { Write-Host "    $msg"; Log $msg }
function Warn([string]$msg) { Write-Host "    WARNING: $msg" -ForegroundColor Yellow; Log "WARN $msg"; [void]$script:Warnings.Add($msg) }
function Fail([string]$msg) {
    Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; Log "FAIL $msg"
    Write-Host "Details are in $LogFile"
    exit 1
}

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [switch]$AllowFail)
    Log ("RUN {0} {1}" -f $Exe, ($Arguments -join " "))
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments | Out-Host
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
    if ($code -ne 0 -and -not $AllowFail) { throw ("{0} failed (exit code {1})" -f (Split-Path -Leaf $Exe), $code) }
    return $code
}

function AskYesNo([string]$question, [bool]$default) {
    if ($Yes) { return $default }
    $hint = "y/N"
    if ($default) { $hint = "Y/n" }
    $answer = Read-Host ("{0} [{1}]" -f $question, $hint)
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim().ToLower().StartsWith("y")
}

function Download([string]$Url, [string]$Dest) {
    Log "DOWNLOAD $Url -> $Dest"
    $dir = Split-Path -Parent $Dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 3 --retry-delay 3 -C - -o $Dest $Url
        if ($LASTEXITCODE -ne 0) {
            if (Test-Path $Dest) { Remove-Item -Force $Dest }
            & $curl.Source -L --fail --retry 3 --retry-delay 3 -o $Dest $Url
            if ($LASTEXITCODE -ne 0) { throw "download failed: $Url" }
        }
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    }
}

function Expand([string]$Zip, [string]$Dest) {
    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        & $tar.Source -xf $Zip -C $Dest
        if ($LASTEXITCODE -eq 0) { return }
    }
    Expand-Archive -Path $Zip -DestinationPath $Dest -Force
}

function Get-Sha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower() }

function Get-OllamaVersion([string]$exe) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $text = ""
    try { $text = (& $exe --version 2>&1 | ForEach-Object { "$_" }) -join " " } catch { $text = "" }
    finally { $ErrorActionPreference = $old }
    if ($text -match "(\d+\.\d+\.\d+)") { return $Matches[1] }
    return ""
}

# ---- start ----------------------------------------------------------------------------------------------------------
Log "==== install started (repo $Repo) ===="
Write-Host "IVAR SMP (Social Media Prepper) installer" -ForegroundColor White
Write-Host "Made by IVAR Studios. Folder: $Repo"

Step "Checking this computer"
if (-not [Environment]::Is64BitOperatingSystem) { Fail "64-bit Windows is required." }
$os = [Environment]::OSVersion.Version
Info ("Windows {0}.{1} build {2}" -f $os.Major, $os.Minor, $os.Build)
if ($os.Major -lt 10) { Fail "Windows 10 or 11 is required." }

$GpuName = ""; $GpuVram = 0
$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if (-not $smi) {
    $cand = Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
    if (Test-Path $cand) { $smi = Get-Item $cand }
}
if ($smi) {
    $smiPath = $smi.Source
    if (-not $smiPath) { $smiPath = $smi.FullName }
    try {
        foreach ($r in @(& $smiPath --query-gpu=name,memory.total --format=csv,noheader,nounits)) {
            $p = $r -split ","
            if ($p.Count -ge 2) {
                $mem = [math]::Round([double]($p[1].Trim()) / 1024.0, 1)
                if ($mem -gt $GpuVram) { $GpuName = $p[0].Trim(); $GpuVram = $mem }
            }
        }
    } catch { Warn "nvidia-smi failed: $_" }
}
if ($GpuName) { Info "GPU: $GpuName, $GpuVram GB" } else { Info "No NVIDIA GPU found." }

if (-not $ClaudeOnly -and $GpuVram -lt 8) {
    Write-Host "    Without an NVIDIA GPU with 8 GB or more, the local vision model is very slow."
    Write-Host "    The Claude API works well instead (needs an API key; images are sent to Anthropic)."
    if (-not (AskYesNo "Install the local model runtime (Ollama) anyway?" $false)) { $ClaudeOnly = $true }
}

# ---- uv and Python --------------------------------------------------------------------------------------------------
Step "Installing uv (Python package manager)"
$uvDir = Join-Path $Tools "uv"
$uv = Join-Path $uvDir "uv.exe"
$uvHave = ""
if (Test-Path $uv) { $uvHave = ((& $uv --version) -join " ") }
if ($uvHave -notmatch ("^uv " + [regex]::Escape($UvVersion) + "(\s|$)")) {
    $oldDir = $env:UV_INSTALL_DIR
    $oldPath = $env:UV_NO_MODIFY_PATH
    try {
        $env:UV_INSTALL_DIR = $uvDir
        $env:UV_NO_MODIFY_PATH = "1"
        # uv's installer runs in its own PowerShell: run in this one, it redefines functions such as Download
        $code = Invoke-Native "powershell.exe" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "Invoke-RestMethod -Uri 'https://astral.sh/uv/$UvVersion/install.ps1' | Invoke-Expression") -AllowFail
        if ($code -ne 0) { throw "the uv installer exited with code $code" }
    } catch { Fail "Could not install uv: $_" }
    finally {
        $env:UV_INSTALL_DIR = $oldDir
        $env:UV_NO_MODIFY_PATH = $oldPath
    }
    if (-not (Test-Path $uv)) { Fail "uv was installed but $uv was not found." }
}
Info ("uv: " + ((& $uv --version) -join " "))

Step "Installing Python $PythonVersion and IVAR SMP"
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
try {
    Invoke-Native $uv @("python", "install", $PythonVersion) | Out-Null
    if (-not (Test-Path $Py)) { Invoke-Native $uv @("venv", (Join-Path $Repo ".venv"), "--python", $PythonVersion) | Out-Null }
    Push-Location $Repo
    try { Invoke-Native $uv @("pip", "install", "--python", $Py, "-e", ".") | Out-Null } finally { Pop-Location }
} catch { Fail "Python setup failed: $_" }

# ---- ExifTool -------------------------------------------------------------------------------------------------------
Step "Installing ExifTool $ExifToolVersion"
$exeDir = Join-Path $Tools "exiftool"
$exe = Join-Path $exeDir "exiftool.exe"
$haveVersion = ""
if (Test-Path $exe) { try { $haveVersion = (& $exe -ver).Trim() } catch { $haveVersion = "" } }
if ($haveVersion -ne $ExifToolVersion) {
    $zip = Join-Path $env:TEMP "exiftool-${ExifToolVersion}_64.zip"
    $ok = $false
    foreach ($url in @("https://sourceforge.net/projects/exiftool/files/exiftool-${ExifToolVersion}_64.zip/download",
                       "https://exiftool.org/exiftool-${ExifToolVersion}_64.zip")) {
        try {
            if (Test-Path $zip) { Remove-Item -Force $zip }
            Download $url $zip
            if ((Get-Sha256 $zip) -eq $ExifToolSha256) { $ok = $true; break }
            Warn "ExifTool checksum mismatch from $url"
        } catch { Warn "ExifTool download failed from ${url}: $_" }
    }
    if (-not $ok) { Fail "Could not download a verified ExifTool." }
    $tmp = Join-Path $env:TEMP "ivar-smp-exiftool"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand $zip $tmp
    $inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if (Test-Path $exeDir) { Remove-Item -Recurse -Force $exeDir }
    New-Item -ItemType Directory -Force -Path $exeDir | Out-Null
    Copy-Item -Recurse -Force (Join-Path $inner.FullName "exiftool_files") (Join-Path $exeDir "exiftool_files")
    Copy-Item -Force (Join-Path $inner.FullName "exiftool(-k).exe") $exe
    Remove-Item -Recurse -Force $tmp
    Remove-Item -Force $zip
}
Info ("ExifTool " + (& $exe -ver))

# ---- Ollama ---------------------------------------------------------------------------------------------------------
if ($ClaudeOnly) {
    Step "Skipping Ollama: this computer uses the Claude API"
} else {
    Step "Installing Ollama $OllamaVersion (runs the vision model on this computer)"
    $ollamaDir = Join-Path $Tools "ollama"
    $ollamaExe = Join-Path $ollamaDir "ollama.exe"
    $haveOllama = ""
    if (Test-Path $ollamaExe) { $haveOllama = Get-OllamaVersion $ollamaExe }
    if ($haveOllama -ne $OllamaVersion) {
        $zip = Join-Path $env:TEMP "ollama-windows-amd64.zip"
        try {
            Info "Downloading Ollama (1-2 GB, may take a while)..."
            Download $OllamaUrl $zip
            if ((Get-Sha256 $zip) -ne $OllamaSha256) { Remove-Item -Force $zip; throw "checksum mismatch" }
            Info "checksum verified"
            Expand $zip $ollamaDir
            Remove-Item -Force $zip
            if (-not (Test-Path $ollamaExe)) {
                $found = Get-ChildItem -Path $ollamaDir -Recurse -Filter "ollama.exe" | Select-Object -First 1
                if ($found) { Get-ChildItem -Path $found.DirectoryName | Move-Item -Destination $ollamaDir -Force }
            }
        } catch { Warn "Ollama install failed: $_. The local model stays off until you run install.bat again; the Claude API still works." }
    }
    if (Test-Path $ollamaExe) { Info ("Ollama " + (Get-OllamaVersion $ollamaExe)) }
}

# ---- shortcuts ------------------------------------------------------------------------------------------------------
if (-not $NoShortcuts) {
    Step "Creating shortcuts"
    try {
        $shell = New-Object -ComObject WScript.Shell
        $ico = Join-Path $Repo "smp\static\smp-icon.ico"
        $targets = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))
        foreach ($dir in $targets) {
            $lnk = $shell.CreateShortcut((Join-Path $dir "IVAR SMP.lnk"))
            $lnk.TargetPath = Join-Path $Repo "start.bat"
            $lnk.WorkingDirectory = $Repo
            $lnk.WindowStyle = 7
            $lnk.IconLocation = "$ico,0"
            $lnk.Description = "IVAR SMP: captions, alt text and keywords for finished images"
            $lnk.Save()
        }
        Info "Desktop and Start menu: IVAR SMP"
    } catch { Warn "Could not create shortcuts: $_" }
}

# ---- health check ---------------------------------------------------------------------------------------------------
Step "Health check"
Push-Location $Repo
try { & $Py -m smp doctor; $doctorCode = $LASTEXITCODE } finally { Pop-Location }

Write-Host ""
if ($script:Warnings.Count -gt 0) {
    Write-Host "Finished with warnings:" -ForegroundColor Yellow
    foreach ($w in $script:Warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
} else {
    Write-Host "Install complete." -ForegroundColor Green
}
if ($doctorCode -ne 0) { Write-Host "Some checks failed (see above). Running install.bat again fixes most of them." -ForegroundColor Yellow }
Write-Host "Start IVAR SMP from the desktop shortcut. The first start shows Setup, where you download the vision model"
Write-Host "for this computer or add a Claude API key."
Log "==== install finished (doctor exit $doctorCode, $($script:Warnings.Count) warnings) ===="
exit 0
