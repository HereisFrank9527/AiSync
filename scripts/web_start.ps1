$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".conda\python.exe"
$port = if ($env:AISYNC_WEB_PORT) { $env:AISYNC_WEB_PORT } elseif ($env:AISYNC_BACKEND_PORT) { $env:AISYNC_BACKEND_PORT } else { "27631" }

if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$url = "http://127.0.0.1:$port"
Write-Host "AiSync Web mode"
Write-Host "URL: $url"
Write-Host "Press Ctrl+C to stop."

Push-Location $backendRoot
try {
  & $python -m app.cli --host 127.0.0.1 --port $port
} finally {
  Pop-Location
}
