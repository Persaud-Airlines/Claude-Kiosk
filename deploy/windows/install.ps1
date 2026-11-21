<#
.SYNOPSIS
  Install the DE-TECH-TIVE Master/Host on Windows 10 or 11 Pro.

  Run from an ELEVATED PowerShell window (right-click Start > Terminal (Admin)):
    cd C:\DeTechtive
    powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -PublicUrl https://edu.detechtive.ca

.PARAMETER PublicUrl
  The public HTTPS address kiosks and staff use (your Cloudflare Tunnel hostname).

.PARAMETER PostgresUrl
  Optional. postgresql+asyncpg://user:password@host:5432/detechtive. Omit to use SQLite.
#>
param(
    [string]$PublicUrl = "https://edu.detechtive.ca",
    [string]$PostgresUrl = ""
)

. (Join-Path $PSScriptRoot "common.ps1")

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "    WARNING: $text" -ForegroundColor Yellow }

if (-not (Test-IsAdministrator)) {
    throw "Run this script from an elevated (Administrator) PowerShell window."
}

$root = Get-RepoRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$taskUser = "NT AUTHORITY\SYSTEM"

Write-Step "Checking prerequisites"
$python = Get-PythonExe
Write-Host "    Python: $python"
if ($python -match "\\Users\\") {
    throw ("Python is installed only for your user account ($python). The server runs as SYSTEM and cannot use " +
           "that copy. Uninstall it and reinstall Python 3.12 with 'Install for all users'.")
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js 20+ is required (for building the portal). Install the LTS version from https://nodejs.org/"
}
Write-Host "    Node.js: $(node --version)"
$tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tesseract -and -not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    Write-Warn "Tesseract OCR not found. Card scanning will not work until it is installed:"
    Write-Warn "  https://github.com/UB-Mannheim/tesseract/wiki (tick 'Additional language data' for fra/spa)"
}
if ($root -notlike "C:\*") { Write-Warn "The repository is not on C:. Consider moving it to C:\DeTechtive." }

Write-Step "Checking disk encryption (student data must be encrypted at rest)"
try {
    $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
    if ($bl.ProtectionStatus -eq "On") {
        Write-Host "    BitLocker is on for $($env:SystemDrive)"
    } else {
        Write-Warn "BitLocker is OFF. Turn it on: Settings > Privacy & security > Device encryption, or Control Panel > BitLocker Drive Encryption."
    }
} catch {
    Write-Warn "Could not read BitLocker status ($($_.Exception.Message)). Confirm that $($env:SystemDrive) is encrypted."
}

Write-Step "Setting up the Python environment"
$venvPython = Initialize-BackendEnvironment -BackendDir $backend -Update
New-Item -ItemType Directory -Force -Path (Join-Path $backend "data"), (Join-Path $backend "logs"), (Join-Path $backend "backups") | Out-Null

Write-Step "Creating backend\.env (secrets are generated automatically)"
$initArgs = @("--production", "--public-url", $PublicUrl)
if ($PostgresUrl) { $initArgs += @("--postgres-url", $PostgresUrl) }
Push-Location $backend
& $venvPython scripts\init_env.py @initArgs
Pop-Location

Write-Step "Building the staff portal"
Push-Location $frontend
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
Pop-Location

Write-Step "Keeping the PC awake (the server must stay up)"
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null

Write-Step "Registering the server to start at boot"
$serverScript = Join-Path $root "deploy\windows\start-server.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$serverScript`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask -TaskName "DE-TECH-TIVE Server" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Step "Scheduling nightly backups (02:15)"
$backupScript = Join-Path $root "deploy\windows\backup.ps1"
$bAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$backupScript`""
$bTrigger = New-ScheduledTaskTrigger -Daily -At "02:15"
$bSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "DE-TECH-TIVE Backup" -Action $bAction -Trigger $bTrigger `
    -Principal $principal -Settings $bSettings -Force | Out-Null

Write-Step "Starting the server and checking health"
Start-ScheduledTask -TaskName "DE-TECH-TIVE Server"
$healthy = $false
for ($i = 0; $i -lt 30 -and -not $healthy; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3
        $healthy = ($r.status -eq "ok")
    } catch { }
}
if ($healthy) { Write-Host "    Server is running on 127.0.0.1:8000" }
else { Write-Warn "The server did not answer. See backend\logs\server.log" }

Write-Step "Cloudflare Tunnel"
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf -and (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe")) {
    $cf = @{ Source = "C:\Program Files (x86)\cloudflared\cloudflared.exe" }
}
if (-not $cf) {
    Write-Warn "cloudflared is not installed. Install it from https://github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.msi), then run:"
    Write-Warn "  cloudflared service install <TUNNEL-TOKEN>"
} else {
    $secure = Read-Host "Paste the tunnel token from the Cloudflare dashboard (leave blank to skip)" -AsSecureString
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if ($token) {
        & $cf.Source service install $token
        if ($LASTEXITCODE -eq 0) { Write-Host "    Tunnel service installed (route $PublicUrl -> http://localhost:8000)" }
        else { Write-Warn "cloudflared service install failed; check the token." }
    } else {
        Write-Host "    Skipped. Run 'cloudflared service install <TOKEN>' later."
    }
    $token = $null
}

Write-Step "Done"
Write-Host "  Portal:           $PublicUrl  (or http://127.0.0.1:8000 on this PC)"
Write-Host "  First admin:      see $backend\data\INITIAL_ADMIN_PASSWORD.txt"
Write-Host "                    log in, change the password, enable MFA, then DELETE that file."
Write-Host "  Logs:             $backend\logs"
Write-Host "  Backups:          $backend\backups (nightly 02:15)"
Write-Host "  Update later:     git pull; powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -PublicUrl $PublicUrl"
