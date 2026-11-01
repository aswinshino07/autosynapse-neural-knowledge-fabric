$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonOptions = @()
$pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pythonLauncher) { $pythonOptions += $pythonLauncher.Source }
$pythonLauncher = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonLauncher) { $pythonOptions += $pythonLauncher.Source }
if ($env:USERPROFILE) { $pythonOptions += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') }
$pythonExe = $null
foreach ($candidate in $pythonOptions | Select-Object -Unique) {
  if (-not (Test-Path -LiteralPath $candidate)) { continue }
  try {
    & $candidate -c 'import sys; print(sys.version_info.major)' *> $null
    if ($LASTEXITCODE -eq 0) { $pythonExe = $candidate; break }
  } catch { }
}
if (-not $pythonExe) { throw 'Python 3.10+ was not found. Install Python and rerun .\install.ps1.' }
Push-Location $appRoot
try {
  & $pythonExe -m venv .venv
  & (Join-Path $appRoot '.venv\Scripts\python.exe') -m pip install --upgrade pip
  & (Join-Path $appRoot '.venv\Scripts\python.exe') -m pip install -r requirements.txt
  Write-Host 'AUTOSYNAPSE installed. Run .\start.ps1 to launch the dashboard.' -ForegroundColor Cyan
} finally { Pop-Location }
