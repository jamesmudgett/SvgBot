# Start SvgBot backend + frontend on Windows (PowerShell only).
# Do NOT run with bash (./run.ps1). Use instead:
#   PowerShell:  .\run.ps1
#   CMD:         run.cmd
#   Git Bash:    ./run.sh
$ErrorActionPreference = "Stop"$Root = $PSScriptRoot
$BackendPort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "5173" }

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating backend venv..."
    python -m venv (Join-Path $Root "backend\.venv")
}

Write-Host "Installing backend deps if needed..."
& $venvPython -m pip install -q -r (Join-Path $Root "backend\requirements.txt")

if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Push-Location (Join-Path $Root "frontend")
    npm install
    Pop-Location
}

$env:PYTHONPATH = Join-Path $Root "backend"

# Stale shell STARVECTOR_ENABLED=false overrides backend/.env in some setups — drop it.
Remove-Item Env:STARVECTOR_ENABLED -ErrorAction SilentlyContinue

# Stop any stale backend processes BEFORE starting a new one. We need to be more
# aggressive than just "things bound to BackendPort" because a uvicorn that crashed
# mid-import (e.g. WinError 6714 on transformers) never reaches the port-bind step
# but still keeps file handles open inside the venv and blocks new imports.
$portListeners = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
foreach ($c in $portListeners) {
    $procId = $c.OwningProcess
    if ($procId -and $procId -ne 0) {
        Write-Host "Stopping prior process on port ${BackendPort} (PID $procId)..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

$staleVenvProcs = Get-Process python, pythonw, uvicorn -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like (Join-Path $Root "backend\.venv\*") }
foreach ($p in $staleVenvProcs) {
    Write-Host "Stopping stale venv process: $($p.ProcessName) (PID $($p.Id))"
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

Write-Host "Starting backend http://127.0.0.1:${BackendPort}"
# Important: limit `--reload` scope to ./app so watchfiles ignores .venv and the
# StarVector/HF model cache. Otherwise a model download (or .pyc regeneration)
# triggers a worker reload mid-import on Windows and surfaces as WinError 6714
# when the new worker re-imports transformers while the old worker still holds
# file handles inside .venv.
Start-Process -FilePath $venvPython -ArgumentList @(
    "-m", "uvicorn", "app.main:app",
    "--reload",
    "--reload-dir", "app",
    "--reload-exclude", "*.pyc",
    "--reload-exclude", ".venv/*",
    "--host", "0.0.0.0", "--port", $BackendPort
) -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "Starting frontend http://localhost:${FrontendPort}"
Push-Location (Join-Path $Root "frontend")
npm run dev -- --host --port $FrontendPort
