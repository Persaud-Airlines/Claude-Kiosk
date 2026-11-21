# Started by the "DE-TECH-TIVE Server" scheduled task at boot (and restarted by Task Scheduler if it exits).
# Each run writes backend\logs\server-<timestamp>.log (uvicorn/app output) and server-<timestamp>-error.log.
. (Join-Path $PSScriptRoot "common.ps1")

$backend = Join-Path (Get-RepoRoot) "backend"
New-Item -ItemType Directory -Force -Path (Join-Path $backend "logs"), (Join-Path $backend "data") | Out-Null

$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment missing. Run deploy\windows\install.ps1 first." }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path $backend "logs\server-$stamp.log"
$err = Join-Path $backend "logs\server-$stamp-error.log"
$args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
          "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1")

$proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $backend -NoNewWindow `
    -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
exit $proc.ExitCode
