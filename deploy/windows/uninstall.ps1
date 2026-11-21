# Removes the scheduled tasks and the Cloudflare Tunnel service. Your data, backups and .env are kept.
. (Join-Path $PSScriptRoot "common.ps1")
if (-not (Test-IsAdministrator)) { throw "Run from an elevated PowerShell window." }

foreach ($name in @("DE-TECH-TIVE Server", "DE-TECH-TIVE Backup")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed scheduled task: $name"
    }
}
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cf) { & $cf.Source service uninstall; Write-Host "Removed the Cloudflare Tunnel service" }
Write-Host "Data, backups and backend\.env were kept. Delete the folder yourself if you no longer need it."
