param(
  [string]$InstallDir = "$env:LOCALAPPDATA\AiSync",
  [int]$StartupSeconds = 18
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $InstallDir "aisync.exe"
$diag = Join-Path $env:APPDATA "com.aisync.app\startup-diagnostics.txt"
$logDir = Join-Path $env:LOCALAPPDATA "com.aisync.app\logs"

if (-not (Test-Path -LiteralPath $exe)) {
  throw "Installed AiSync exe not found: $exe"
}

Remove-Item -LiteralPath `
  (Join-Path $logDir "backend.last_start.txt"), `
  (Join-Path $logDir "backend.err.log"), `
  (Join-Path $logDir "frontend.boot.log"), `
  $diag `
  -Force -ErrorAction SilentlyContinue

$process = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds $StartupSeconds

Write-Host "app_pid=$($process.Id) running=$(-not $process.HasExited)"
Write-Host "diagnostics_path=$diag"

if (-not (Test-Path -LiteralPath $diag)) {
  if (-not $process.HasExited) {
    $null = $process.CloseMainWindow()
    Start-Sleep -Seconds 3
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
  }
  throw "startup diagnostics not found"
}

$diagnostics = Get-Content -Raw -Encoding UTF8 -LiteralPath $diag
Write-Host $diagnostics

if ($diagnostics -notmatch "backend_health=true") {
  throw "backend health check did not pass"
}
if ($diagnostics -match "target\\debug") {
  throw "diagnostics points to target\\debug"
}

$closed = $process.CloseMainWindow()
Write-Host "close_main_window=$closed"
Wait-Process -Id $process.Id -Timeout 20 -ErrorAction SilentlyContinue
if (-not $process.HasExited) {
  Stop-Process -Id $process.Id -Force
}

Start-Sleep -Seconds 5
$remaining = Get-Process aisync,python,pythonw -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like "$InstallDir*" } |
  Select-Object ProcessName,Id,Path

if ($remaining) {
  $remaining | Format-Table -AutoSize
  throw "managed app processes remain after close"
}

Write-Host "smoke test passed"
