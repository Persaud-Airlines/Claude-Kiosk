# Shared helpers for the DE-TECH-TIVE Windows scripts (Windows 10/11 Pro, Windows PowerShell 5.1+).

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Returns the full path of a Python 3.11+ interpreter (prefers the py launcher, then python on PATH).
function Get-PythonExe {
    $probe = 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $out = & $cmd.Source @($c.Args) -c $probe 2>$null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($code -eq 0 -and $out) {
            return ($out | Select-Object -First 1).ToString().Trim()
        }
    }
    throw ("Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/windows/ " +
           "and tick 'Add python.exe to PATH' and 'Install for all users'.")
}

# Creates backend\.venv on first use and installs the requirements. Returns the venv's python.exe.
function Initialize-BackendEnvironment {
    param([string]$BackendDir, [switch]$Update)

    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        $base = Get-PythonExe
        Write-Host "Creating virtual environment with $base"
        & $base -m venv (Join-Path $BackendDir ".venv")
        if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
        $Update = $true
    }
    if ($Update) {
        Write-Host "Installing Python requirements (this can take a few minutes)..."
        & $venvPython -m pip install --quiet --upgrade pip
        & $venvPython -m pip install --quiet -r (Join-Path $BackendDir "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "pip could not install requirements.txt" }
    }
    return $venvPython
}
