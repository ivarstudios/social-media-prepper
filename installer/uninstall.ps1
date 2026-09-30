<#
  IVAR SMP uninstaller for Windows (PowerShell 5.1+). Run via uninstall.bat.
  Removes everything SMP installed, wherever the installer put it: the programs, the vision models, SMP's data, the
  Python environment, the shortcuts and the installer's files in this folder. A downloaded copy of SMP is then deleted
  too (uninstall.bat does that last); a git clone keeps its code.
  Only SMP's own files go: a folder that also holds other files keeps them.

  Options (pass to uninstall.bat):
    -Yes   no questions
  Exit code: 0 done (or nothing removed), 1 stopped, 2 done and uninstall.bat deletes this folder.
#>
[CmdletBinding()]
param([switch]$Yes)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$LogFile = ""                                  # a log in this folder would go with the rest
. (Join-Path $PSScriptRoot "common.ps1")

# what SMP puts in each folder; anything else there stays
$Own = @{
    models = @("blobs", "manifests", "metadata")
    tools  = @("uv", "python", "uv-cache", "exiftool", "ollama", ".download")
    data   = @("settings.json", "smp.sqlite", "smp.sqlite-journal", "smp.sqlite-wal", "smp.sqlite-shm", "thumbs",
               "geonames", "ollama-models")
    app    = @(".venv", "ivar_smp.egg-info", "install.log", "locations.json", ".pytest_cache")
}
$Labels = @{ models = "Models"; tools = "Programs"; data = "Data" }

function Remove-Path([string]$path) {
    # rmdir /s removes junctions without following them (uv links Python versions with them); PowerShell 5.1's
    # Remove-Item -Recurse can delete what a junction points to
    if (Test-Path -LiteralPath $path -PathType Container) { & cmd.exe /c rmdir /s /q $path } else { Remove-Item -Force -LiteralPath $path }
    if (Test-Path -LiteralPath $path) { Warn "Could not remove $path (is something using it?)" }
}

function Remove-Own([string]$folder, [string[]]$names, [string]$label) {
    if (-not (Test-Path -LiteralPath $folder)) { return }
    foreach ($n in $names) {
        $p = Join-Path $folder $n
        if (Test-Path -LiteralPath $p) { Remove-Path $p }
    }
    if (HasFiles $folder) { Info "${label}: removed SMP's files; kept $folder, it holds other files too" }
    else { Remove-Path $folder; Info "${label}: removed $folder" }
}

function Get-ModelNames([string]$models) {
    $root = Join-Path $models "manifests\registry.ollama.ai"
    if (-not (Test-Path -LiteralPath $root)) { return @() }
    return @(Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
        $ns = $_.Directory.Parent.Name
        if ($ns -eq "library") { "{0}:{1}" -f $_.Directory.Name, $_.Name } else { "{0}/{1}:{2}" -f $ns, $_.Directory.Name, $_.Name }
    })
}

function Get-OwnShortcuts {
    # only shortcuts that start this copy (another copy's installer may have made them since)
    $out = @()
    try {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))) {
            $lnk = Join-Path $dir "IVAR SMP.lnk"
            if ((Test-Path -LiteralPath $lnk) -and (Same $shell.CreateShortcut($lnk).TargetPath (Join-Path $Repo "start.bat"))) { $out += $lnk }
        }
    } catch { Warn "Could not read the shortcuts: $_" }
    return $out
}

# ---- what goes ------------------------------------------------------------------------------------------------------
Write-Host "IVAR SMP uninstaller" -ForegroundColor White
$f = Get-CurrentFolders (Get-SavedLocations)
$isClone = Test-Path -LiteralPath (Join-Path $Repo ".git")
$links = Get-OwnShortcuts

Step "This removes"
foreach ($k in "models", "tools", "data") {
    if (HasFiles $f[$k]) { Info ("{0,-9} {1}   ({2})" -f "$($Labels[$k]):", $f[$k], (Size $f[$k])) }
    if ($k -eq "models") {
        $names = Get-ModelNames $f.models
        if ($names) { Info ("           with the models {0}" -f ($names -join ", ")) }
    }
}
Info "App files: the Python environment (.venv) and the installer's files in $Repo"
if ($links) { Info "Shortcuts: IVAR SMP on the desktop and in the Start menu" }
if ($isClone) { Info "The code stays: this folder is a git clone." }
else { Info "The app:   $Repo itself, last" }
Info "A folder that also holds other files keeps them."
if (-not $Yes -and -not (AskYesNo "Remove all of this?" $false)) {
    Write-Host "Nothing was removed."
    exit 0
}

if (Test-SmpRunning) { Fail "IVAR SMP is running. Close it (its window and its console window), then run this again." }
Stop-OwnOllama $f.tools

# ---- remove ---------------------------------------------------------------------------------------------------------
Step "Removing"
foreach ($k in "models", "tools", "data") { Remove-Own $f[$k] $Own[$k] $Labels[$k] }
foreach ($n in $Own.app) { $p = Join-Path $Repo $n; if (Test-Path -LiteralPath $p) { Remove-Path $p } }
Get-ChildItem -LiteralPath $Repo -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Path $_.FullName }
Info "App files: removed"
foreach ($lnk in $links) { Remove-Path $lnk }
if ($links) { Info "Shortcuts: removed" }
if (-not (Same $f.data $LegacyData) -and (HasFiles $LegacyData)) {
    Info "Left ${LegacyData}: where an earlier version kept its data. Delete it if no other copy of SMP uses it."
}

Write-Host ""
if ($script:Warnings.Count -gt 0) {
    Write-Host "Finished with warnings:" -ForegroundColor Yellow
    foreach ($w in $script:Warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
}
if ($isClone) {
    Write-Host "IVAR SMP is uninstalled. The code is still in $Repo (a git clone): delete the folder yourself if you want." -ForegroundColor Green
    exit 0
}
if ($Yes -or (AskYesNo "Delete the app folder $Repo too?" $true)) { exit 2 }
Write-Host "IVAR SMP is uninstalled. The app folder $Repo is still there." -ForegroundColor Green
exit 0
