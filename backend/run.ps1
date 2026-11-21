<#
.SYNOPSIS
  Start the DE-TECH-TIVE server from this folder (Windows 10/11).

.EXAMPLE
  .\run.ps1                 # development: http://localhost:8000, reloads on code changes, LAN-reachable
  .\run.ps1 -Production     # production: 127.0.0.1:8000 (for the Cloudflare Tunnel); needs backend\.env from install.ps1
  .\run.ps1 -Update         # reinstall Python requirements after an update
#>
param(
    [switch]$Production,
    [switch]$Update,
    [int]$Port = 8000
)

. (Join-Path $PSScriptRoot "..\deploy\windows\common.ps1")
Set-Location -LiteralPath $PSScriptRoot

$python = Initialize-BackendEnvironment -BackendDir $PSScriptRoot -Update:$Update
if (-not (Test-Path ".env")) {
    Write-Host "No .env found; creating one with fresh secrets (development defaults)."
    & $python scripts\init_env.py
}
New-Item -ItemType Directory -Force -Path data, logs, backups | Out-Null

if ($Production) {
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 `
        --proxy-headers --forwarded-allow-ips 127.0.0.1
} else {
    Write-Host "Portal: http://localhost:$Port   (LAN: http://<this-pc-ip>:$Port)"
    & $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
}
