param(
  [int]$Port = 27631,
  [switch]$Lan
)

$ErrorActionPreference = "Stop"

$packageRoot = $PSScriptRoot
$venvPython = Join-Path $packageRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
  & (Join-Path $packageRoot "setup.ps1")
}
if (-not (Test-Path -LiteralPath $venvPython)) {
  throw "AiSync Python environment is not ready. Run setup.ps1 and review the error output."
}

$hostAddress = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$url = "http://127.0.0.1:$Port"
Write-Host "AiSync Web v$(Get-Content -LiteralPath (Join-Path $packageRoot 'VERSION') -Raw)"
Write-Host "URL: $url"
if ($Lan) {
  Write-Host "LAN mode has no authentication. Use only on a trusted network." -ForegroundColor Yellow
}
Write-Host "Press Ctrl+C to stop."

Push-Location (Join-Path $packageRoot "backend")
try {
  & $venvPython -m app.cli --host $hostAddress --port $Port
} finally {
  Pop-Location
}
