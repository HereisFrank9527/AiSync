$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$resourceDir = Join-Path $repoRoot "frontend\src-tauri\resources\backend"
$builtBackend = Join-Path $backendRoot "dist\aisync-backend.exe"
$resourceBackend = Join-Path $resourceDir "aisync-backend.exe"

& (Join-Path $repoRoot "scripts\build_backend.ps1")

if (-not (Test-Path $builtBackend)) {
  throw "Backend executable not found: $builtBackend"
}

New-Item -ItemType Directory -Force -Path $resourceDir | Out-Null
Copy-Item -LiteralPath $builtBackend -Destination $resourceBackend -Force
