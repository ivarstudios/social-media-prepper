<#
  IVAR SMP installer for Windows 10/11 (PowerShell 5.1+). Run via install.bat (start.bat runs it on first use).
  Safe to re-run: it repairs and updates. No admin rights needed.

  It asks where three things go, keeps the answers in locations.json in this folder, and moves what's already there
  when a folder changes (run it again to change one):
    Programs  uv, Python, ExifTool, Ollama (about 2 GB)          default: tools\ in this folder
    Models    the vision models (6 to 36 GB each)                default: data\ollama-models in this folder
    Data      settings, answer cache, thumbnails, place names    default: data\ in this folder
              and the undo record
  So by default everything stays in this folder. The app and its Python environment (.venv) always do. Apart from
  the shortcuts, nothing goes anywhere else: uv, Python, the package cache and the downloads all stay in the programs
  folder. uninstall.bat removes all of it.

  Options (pass to install.bat):
    -Yes              no questions: keep the folders (or use the ones given below) and accept all defaults
    -ClaudeOnly       don't install Ollama: use the Claude API only (no local model)
    -NoShortcuts      don't create desktop and Start menu shortcuts
    -ToolsDir <dir>   the programs folder
    -ModelsDir <dir>  the models folder
    -DataDir <dir>    the data folder
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$ClaudeOnly,
    [switch]$NoShortcuts,
    [string]$ToolsDir = "",
    [string]$ModelsDir = "",
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $Repo "install.log"
. (Join-Path $PSScriptRoot "common.ps1")

# ---- pinned versions (the tested builds) ---------------------------------------------------------------------------
$UvVersion = "0.12.18"
$PythonVersion = "3.12"
$ExifToolVersion = "13.59"
$ExifToolSha256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"
$OllamaVersion = "0.34.4"
$OllamaUrl = "https://github.com/ollama/ollama/releases/download/v$OllamaVersion/ollama-windows-amd64.zip"
$OllamaSha256 = "535193f38f3344e5b08f5d1c171c31ce11aa17f0124ff69ae26d8ec7fe06fa62"

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

# ---- folders --------------------------------------------------------------------------------------------------------
function FreeSpace([string]$path) {
    try {
        $root = [IO.Path]::GetPathRoot($path)
        if ($root -notmatch '^[A-Za-z]:\\$') { return "" }
        return "{0} has {1:N0} GB free" -f $root.TrimEnd('\'), ((New-Object IO.DriveInfo $root).AvailableFreeSpace / 1GB)
    } catch { return "" }
}

function Normalize-Folder([string]$text) {
    # a typed or pasted folder as a full path ("" when it isn't one): quotes off, %VARIABLES% expanded
    $t = [Environment]::ExpandEnvironmentVariables($text.Trim().Trim('"', "'").Trim()).Replace('/', '\')
    if ($t -notmatch '^([A-Za-z]:\\|\\\\[^\\]+\\[^\\]+)') { return "" }
    try { return [IO.Path]::GetFullPath($t).TrimEnd('\') } catch { return "" }
}

function Folder-Problem([string]$path, [string]$key) {
    # why $path can't be the $key folder, or "" when it can
    if (-not $path) { return "Type a full path, for example D:\IVAR-SMP\$key." }
    if ($path -match '^[A-Za-z]:$' -or $path -match '^\\\\[^\\]+\\[^\\]+$') {
        return "Pick a folder, not a whole drive (for example $path\IVAR-SMP\$key)."
    }
    if (Same $path $Repo) { return "Pick a folder of its own, not the app folder." }
    foreach ($other in @($New.Keys)) {
        if ($other -ne $key -and (Same $New[$other] $path)) { return "That's already the $($Labels[$other].ToLower()) folder: pick another one." }
    }
    $old = $Old[$key]
    if (-not (Same $path $old) -and (Test-Inside $path $old) -and (HasFiles $old)) {
        return "It can't go inside the folder it's moving out of ($old)."
    }
    try {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
        $probe = Join-Path $path ".smp-write-test"
        [IO.File]::WriteAllText($probe, "ok")
        Remove-Item -Force -LiteralPath $probe
    } catch { return "SMP can't write there: $($_.Exception.Message)" }
    return ""
}

function Choose-Folder([string]$key, [string]$given, [string]$current) {
    if ($given -or $Yes) {
        $path = $current
        if ($given) { $path = Normalize-Folder $given }
        $problem = Folder-Problem $path $key
        if ($problem) { Fail "$($Labels[$key]) folder '$(if ($given) { $given } else { $current })': $problem" }
        Info ("{0,-9} {1}" -f "$($Labels[$key]):", $path)
        return $path
    }
    Write-Host ""
    Write-Host "    $($About[$key])"
    $facts = @()
    if (HasFiles $current) { $facts += "holds $(Size $current)" }
    $free = FreeSpace $current
    if ($free) { $facts += $free }
    Write-Host ("      {0}" -f $current) -ForegroundColor White -NoNewline
    if ($facts) { Write-Host ("   ({0})" -f ($facts -join ", ")) -ForegroundColor DarkGray } else { Write-Host "" }
    while ($true) {
        $answer = Read-Host "      Press Enter to keep it, or type another folder"
        $path = $current
        if (-not [string]::IsNullOrWhiteSpace($answer)) { $path = Normalize-Folder $answer }
        $problem = Folder-Problem $path $key
        if (-not $problem) { Log "folder $key = $path"; return $path }
        Write-Host "      $problem" -ForegroundColor Yellow
    }
}

function Save-Locations([hashtable]$loc) {
    # only folders that differ from the default, so a moved app folder keeps its tools\ with it
    $record = [ordered]@{}
    if (-not (Same $loc.tools $DefaultTools)) { $record["tools"] = $loc.tools }
    if (-not (Same $loc.models (Join-Path $loc.data "ollama-models"))) { $record["models"] = $loc.models }
    if (-not (Same $loc.data $DefaultData)) { $record["data"] = $loc.data }
    if ($record.Count -gt 0) {
        [IO.File]::WriteAllText($LocationsFile, (ConvertTo-Json $record), (New-Object Text.UTF8Encoding $false))
    } elseif (Test-Path -LiteralPath $LocationsFile) {
        Remove-Item -Force -LiteralPath $LocationsFile
    }
}

function Move-Folder([string]$From, [string]$To, [string[]]$Keep) {
    # everything in $From into $To, except the folders in $Keep that lie inside $From (they stay where they are)
    $stay = @($Keep | Where-Object { $_ -and -not (Same $_ $From) -and (Test-Inside $_ $From) -and (Test-Path -LiteralPath $_) })
    if ((Test-Path -LiteralPath $To) -and -not (HasFiles $To)) { Remove-Item -Force -LiteralPath $To }
    if ($stay.Count -eq 0 -and -not (Test-Path -LiteralPath $To) -and (Same ([IO.Path]::GetPathRoot($From)) ([IO.Path]::GetPathRoot($To)))) {
        try {       # same drive: a rename, instant
            $parent = Split-Path -Parent $To
            if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            [IO.Directory]::Move($From, $To)
            return
        } catch { Log "rename failed, copying instead: $_" }
    }
    # /IS /IT: files already there are moved too, so nothing stays behind in $From
    $rc = @($From, $To, "/E", "/MOVE", "/IS", "/IT", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($stay.Count -gt 0) { $rc += "/XD"; $rc += $stay }
    Log ("RUN robocopy {0}" -f ($rc -join " "))
    $out = & robocopy.exe @rc
    $code = $LASTEXITCODE
    foreach ($line in @($out)) { if ("$line".Trim()) { Log "robocopy: $line" } }
    if ($code -ge 8) { throw "some files couldn't be moved (robocopy exit code $code)" }
    if ((Test-Path -LiteralPath $From) -and -not (HasFiles $From)) { Remove-Item -Force -LiteralPath $From }
}

function Get-VenvHome([string]$venv) {
    $cfg = Join-Path $venv "pyvenv.cfg"
    if (Test-Path -LiteralPath $cfg) {
        foreach ($line in Get-Content -LiteralPath $cfg) { if ($line -match '^\s*home\s*=\s*(.+?)\s*$') { return $Matches[1] } }
    }
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

# ---- where things go ------------------------------------------------------------------------------------------------
Step "Choosing folders"
$Labels = @{ tools = "Programs"; models = "Models"; data = "Data" }
$About = @{
    tools  = "Programs: uv, Python, ExifTool and Ollama (about 2 GB)"
    models = "Models: the vision model, 6 to 36 GB, downloaded from Setup in the app"
    data   = "Data: settings, answer cache, thumbnails, place names and the undo record (grows as SMP is used)"
}
if ($ClaudeOnly) { $About.tools = "Programs: uv, Python and ExifTool (about 250 MB)" }

# where things are now: the folders chosen last time, else the defaults
$saved = Get-SavedLocations
$Old = Get-CurrentFolders $saved
$Venv = Join-Path $Repo ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$installedHere = (Test-Path $Py) -or (Test-Path -LiteralPath $LocationsFile)
$dataNow = $Old.data
if (-not $saved.data -and (Same $Old.data $LegacyData)) {
    $dataNow = $DefaultData           # earlier versions kept the data in the user profile: suggest the app folder
    if ($installedHere) { Info "SMP's data is in $LegacyData, where earlier versions kept it: it moves into the app folder." }
}

Info "The app and its Python environment (.venv) stay in $Repo"
if (-not $Yes) { Info "For each folder, press Enter to keep it or type (or paste) another one." }
$New = @{}
$New.tools = Choose-Folder "tools" $ToolsDir $Old.tools
$New.data = Choose-Folder "data" $DataDir $dataNow
$modelsNow = Join-Path $New.data "ollama-models"         # by default the models live in the data folder
if ($saved.models) { $modelsNow = $Old.models }
if ($ClaudeOnly -and -not $ModelsDir) {
    $New.models = $modelsNow
} else {
    $New.models = Choose-Folder "models" $ModelsDir $modelsNow
}

$venvStale = (Test-Path $Py) -and -not (Test-Inside (Get-VenvHome $Venv) (Join-Path $New.tools "python"))
$moves = @("models", "tools", "data" | Where-Object { -not (Same $Old[$_] $New[$_]) -and (HasFiles $Old[$_]) })
if ($moves.Count -gt 0 -and -not $installedHere) {
    # a first install: the default folders may belong to another copy of SMP on this PC, which still uses them
    foreach ($k in $moves) { Info "Left $($Old[$k]) as it is: it may belong to another copy of SMP" }
    $moves = @()
}
if (($moves.Count -gt 0 -or $venvStale) -and (Test-SmpRunning)) {
    Fail "IVAR SMP is running. Close it (its window and its console window), then run this again."
}

$Now = @{ tools = $Old.tools; models = $Old.models; data = $Old.data }
$What = @{ tools = "the programs"; models = "the vision models"; data = "SMP's settings and cache" }
$IfNot = @{ tools = "they're downloaded again"; models = "download the model again from Setup in the app"
            data = "SMP starts with fresh settings" }
foreach ($k in $moves) {
    Write-Host ""
    if (-not (AskYesNo ("    Move {0} ({1}) from {2} to {3}? If not, {4}." -f $What[$k], (Size $Old[$k]), $Old[$k], $New[$k], $IfNot[$k]) $true)) {
        Info "Left in $($Old[$k])"
        continue
    }
    if ($k -ne "data") { Stop-OwnOllama $Old.tools }
    Info ("Moving {0} to {1} (large folders can take a few minutes)..." -f $What[$k], $New[$k])
    $keep = @($Repo)
    foreach ($other in "tools", "models", "data") { if ($other -ne $k) { $keep += $Old[$other]; $keep += $New[$other] } }
    try { Move-Folder $Old[$k] $New[$k] $keep } catch {
        Fail ("Moving {0} stopped: {1}. Close anything that uses them and run this again to move the rest." -f $What[$k], $_)
    }
    $Now[$k] = $New[$k]
    Save-Locations $Now                                    # a later failure mustn't lose track of what moved
}
Save-Locations $New
$Tools = $New.tools
$Downloads = Join-Path $Tools ".download"

# ---- uv and Python --------------------------------------------------------------------------------------------------
Step "Installing uv (Python package manager)"
$uvDir = Join-Path $Tools "uv"
$uv = Join-Path $uvDir "uv.exe"
$uvHave = ""
if (Test-Path $uv) { $uvHave = ((& $uv --version) -join " ") }
if ($uvHave -notmatch ("^uv " + [regex]::Escape($UvVersion) + "(\s|$)")) {
    $oldDir = $env:UV_INSTALL_DIR
    $oldUnmanaged = $env:UV_UNMANAGED_INSTALL
    try {
        # into this folder only: no install receipt (it would take over the user's own `uv self update`), no PATH change
        $env:UV_INSTALL_DIR = $uvDir
        $env:UV_UNMANAGED_INSTALL = $uvDir
        # uv's installer runs in its own PowerShell: run in this one, it redefines functions such as Download
        $code = Invoke-Native "powershell.exe" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "Invoke-RestMethod -Uri 'https://astral.sh/uv/$UvVersion/install.ps1' | Invoke-Expression") -AllowFail
        if ($code -ne 0) { throw "the uv installer exited with code $code" }
    } catch { Fail "Could not install uv: $_" }
    finally {
        $env:UV_INSTALL_DIR = $oldDir
        $env:UV_UNMANAGED_INSTALL = $oldUnmanaged
    }
    if (-not (Test-Path $uv)) { Fail "uv was installed but $uv was not found." }
}
Info ("uv: " + ((& $uv --version) -join " "))

Step "Installing Python $PythonVersion and IVAR SMP"
# Python, its downloads and the package cache go into the programs folder, not the user profile
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
$env:UV_MANAGED_PYTHON = "1"             # only that Python, never one found elsewhere on this PC
$env:UV_LINK_MODE = "copy"               # the cache and .venv can be on different drives
try {
    Invoke-Native $uv @("python", "install", $PythonVersion, "--no-bin", "--no-registry") | Out-Null
    if ($venvStale) { Info "The Python environment used another Python: making it again" }
    if ($venvStale -or -not (Test-Path $Py)) { Invoke-Native $uv @("venv", $Venv, "--python", $PythonVersion, "--clear") | Out-Null }
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
    $zip = Join-Path $Downloads "exiftool-${ExifToolVersion}_64.zip"
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
    $tmp = Join-Path $Downloads "exiftool"
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
        $zip = Join-Path $Downloads "ollama-windows-amd64.zip"
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
if ((Test-Path $Downloads) -and -not (HasFiles $Downloads)) { Remove-Item -Force $Downloads }

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
Write-Host "for this computer or add a Claude API key. To move a folder later, run install.bat again."
Log "==== install finished (doctor exit $doctorCode, $($script:Warnings.Count) warnings) ===="
exit 0
