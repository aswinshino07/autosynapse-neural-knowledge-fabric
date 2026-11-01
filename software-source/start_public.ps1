$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $appRoot '..\..\work\autosynapse_runtime'
$runtimeDir = [System.IO.Path]::GetFullPath($runtimeDir)
$pythonExe = Join-Path $appRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = Join-Path $runtimeDir '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run .\install.ps1 first.' }
$cloudflared = (Get-Command cloudflared.exe -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) { $cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe' }
if (-not (Test-Path -LiteralPath $cloudflared)) { throw 'cloudflared was not found on this machine.' }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$serverLog = Join-Path $runtimeDir 'server.log'
$serverErr = Join-Path $runtimeDir 'server.err'
$server = Start-Process -FilePath $pythonExe -ArgumentList '-m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1' -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $serverLog -RedirectStandardError $serverErr
Set-Content -LiteralPath (Join-Path $runtimeDir 'server.pid') -Value $server.Id
Start-Sleep -Seconds 3
$tunnelLog = Join-Path $runtimeDir 'tunnel.out.log'
$tunnelErr = Join-Path $runtimeDir 'tunnel.err.log'
$tunnel = Start-Process -FilePath $cloudflared -ArgumentList @('tunnel','--url','http://127.0.0.1:8000','--no-autoupdate') -WorkingDirectory $runtimeDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $tunnelLog -RedirectStandardError $tunnelErr
Set-Content -LiteralPath (Join-Path $runtimeDir 'tunnel.pid') -Value $tunnel.Id
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  Start-Sleep -Seconds 1
  $match = Select-String -LiteralPath $tunnelErr -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
  if ($match) { Write-Host "AUTOSYNAPSE public demo: $($match.Matches[0].Value)" -ForegroundColor Cyan; exit 0 }
}
throw "No public URL appeared. Check $tunnelErr and $serverErr."
