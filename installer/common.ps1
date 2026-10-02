# Shared by install.ps1 and uninstall.ps1 (dot-sourced): output, questions, and where SMP's folders are.
# Needs $Repo (the app folder), $LogFile ("" for no log file) and $Yes set first.

$LocationsFile = Join-Path $Repo "locations.json"
$DefaultTools = Join-Path $Repo "tools"
$DefaultData = Join-Path $Repo "data"
$LegacyData = Join-Path $env:LOCALAPPDATA "IVAR-SMP"     # where versions before 0.1.2 kept the data
$script:Warnings = New-Object System.Collections.ArrayList

function Log([string]$msg) {
    if (-not $LogFile) { return }
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
    if ($LogFile) { Write-Host "Details are in $LogFile" }
    exit 1
}

function AskYesNo([string]$question, [bool]$default) {
    if ($Yes) { return $default }
    $hint = "y/N"
    if ($default) { $hint = "Y/n" }
    $answer = Read-Host ("{0} [{1}]" -f $question, $hint)
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim().ToLower().StartsWith("y")
}

function Same([string]$a, [string]$b) { return [string]::Equals($a.TrimEnd('\'), $b.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) }

function Test-Inside([string]$path, [string]$folder) {
    # $path is $folder itself or somewhere inside it
    return ($path.TrimEnd('\') + '\').StartsWith($folder.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

function HasFiles([string]$path) {
    return [bool]((Test-Path -LiteralPath $path) -and (Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue | Select-Object -First 1))
}

function Size([string]$path) {
    $sum = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($sum -ge 1GB) { return "{0:N1} GB" -f ($sum / 1GB) } else { return "{0:N0} MB" -f ($sum / 1MB) }
}

function Get-SavedLocations {
    # the folders chosen when installing (locations.json); a missing one is the default
    $saved = @{}
    if (Test-Path -LiteralPath $LocationsFile) {
        try {
            $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $LocationsFile | ConvertFrom-Json
            foreach ($k in "tools", "models", "data") { if ($j.$k) { $saved[$k] = [string]$j.$k } }
        } catch { Warn "Could not read locations.json ($_): using the default folders." }
    }
    return $saved
}

function Get-CurrentFolders([hashtable]$saved) {
    # where SMP's folders are now, worked out the way the app does it (smp/config.py)
    $f = @{ tools = $DefaultTools; data = $DefaultData }
    if ($saved.tools) { $f.tools = $saved.tools }
    if ($saved.data) { $f.data = $saved.data }
    elseif (-not (Test-Path -LiteralPath $DefaultData) -and (HasFiles $LegacyData)) { $f.data = $LegacyData }
    $f.models = Join-Path $f.data "ollama-models"
    if ($saved.models) { $f.models = $saved.models }
    return $f
}

function Test-SmpRunning {
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop |
                 Where-Object { $_.CommandLine -match '\s-m\s+smp(\s|$)' }).Count -gt 0
    } catch { return $false }
}

function Stop-OwnOllama([string]$toolsDir) {
    # SMP's own Ollama listens on port 11436, runs from the programs folder and keeps the models open
    $ids = @()
    try { $ids += @(Get-NetTCPConnection -LocalPort 11436 -State Listen -ErrorAction Stop | ForEach-Object { $_.OwningProcess }) } catch { }
    $ids += @(Get-Process -Name ollama -ErrorAction SilentlyContinue |
              Where-Object { $_.Path -and (Test-Inside $_.Path $toolsDir) } | ForEach-Object { $_.Id })
    $stopped = $false
    foreach ($id in @($ids | Select-Object -Unique)) {
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like "ollama*") {
            try { Stop-Process -Id $id -Force -ErrorAction Stop; $stopped = $true } catch { }
        }
    }
    if ($stopped) { Info "Stopped SMP's Ollama (the app starts it again when needed)"; Start-Sleep -Seconds 1 }
}

# ---- the firewall rule that lets other computers on the network open SMP ---------------------------------------------
$FirewallRule = "IVAR SMP"      # the same name as in smp/network.py

function Test-FirewallRule { return $null -ne (Get-NetFirewallRule -Name $FirewallRule -ErrorAction SilentlyContinue) }

function Invoke-Elevated([string]$command) {
    # runs a PowerShell command with admin rights (Windows asks first); true when it ran and succeeded
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("`$ErrorActionPreference = 'Stop'; $command"))
    try {
        $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden `
             -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded)
        return $p.ExitCode -eq 0
    } catch { return $false }       # the user said no
}
