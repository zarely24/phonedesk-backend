# Start the backend locally (SQLite, auto-reload). Open http://localhost:8000
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No venv yet. Creating one and installing deps..." -ForegroundColor Yellow
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r (Join-Path $root "requirements.txt")
}
Set-Location $root
Write-Host "Backend on http://localhost:8000  (admin@local / admin1234)" -ForegroundColor Green
& $py -m uvicorn app.main:app --reload --port 8000
