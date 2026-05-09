$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$backendRoot = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".conda\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$logDir = Join-Path $repoRoot ".dev-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-BackendHealth {
  try {
    $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 2
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  } catch {
    return $false
  }
}

$backendProcess = $null
if (-not (Test-BackendHealth)) {
  $backendOut = Join-Path $logDir "backend-dev.out.log"
  $backendErr = Join-Path $logDir "backend-dev.err.log"
  $backendProcess = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "app.cli", "--host", "127.0.0.1", "--port", "8000", "--reload") `
    -WorkingDirectory $backendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru
}

Push-Location $frontendRoot
try {
  & npm run dev
} finally {
  Pop-Location
  if ($backendProcess -and -not $backendProcess.HasExited) {
    Stop-Process -Id $backendProcess.Id -Force
  }
}
