$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = [System.IO.Path]::GetFullPath((Join-Path $appRoot '..\..\work\autosynapse_runtime'))
foreach ($name in @('server','tunnel')) {
  $pidFile = Join-Path $runtimeDir "$name.pid"
  if (-not (Test-Path -LiteralPath $pidFile)) { continue }
  $processId = 0
  if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$processId)) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    $expected = if ($name -eq 'server') { $process.ProcessName -like 'python*' } else { $process.ProcessName -like 'cloudflared*' }
    if ($process -and $expected) { Stop-Process -Id $processId -Force }
  }
  Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}
Write-Host 'AUTOSYNAPSE server and public tunnel stopped.' -ForegroundColor Cyan
