$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $appRoot '.venv\Scripts\python.exe'
$devPython = Join-Path $appRoot '..\..\work\autosynapse_runtime\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $devPython)) {
  $pythonExe = $devPython
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw 'Install dependencies first by running .\install.ps1.'
}
Push-Location $appRoot
try {
  & $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
} finally { Pop-Location }
