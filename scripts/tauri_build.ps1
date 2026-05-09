$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"

& (Join-Path $repoRoot "scripts\prepare_tauri_backend.ps1")

Push-Location $frontendRoot
try {
  & npm run build
} finally {
  Pop-Location
}
