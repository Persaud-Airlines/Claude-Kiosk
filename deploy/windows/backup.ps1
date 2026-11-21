# Started nightly by the "DE-TECH-TIVE Backup" scheduled task. Writes backend\logs\backup-<timestamp>.log.
. (Join-Path $PSScriptRoot "common.ps1")

$backend = Join-Path (Get-RepoRoot) "backend"
New-Item -ItemType Directory -Force -Path (Join-Path $backend "logs") | Out-Null
$python = Join-Path $backend ".venv\Scripts\python.exe"
$log = Join-Path $backend ("logs\backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
$proc = Start-Process -FilePath $python -ArgumentList @("scripts\backup.py") -WorkingDirectory $backend `
    -NoNewWindow -Wait -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log + ".err")
exit $proc.ExitCode
