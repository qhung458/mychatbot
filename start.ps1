$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Chua co .venv. Chay cac lenh cai dat trong README.md truoc.' -ForegroundColor Yellow
    exit 1
}
Write-Host 'OLP Chat: http://127.0.0.1:8000 - Ctrl+C de dung.' -ForegroundColor Cyan
# Single worker: each stream and stop event belong to this one local process.
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
