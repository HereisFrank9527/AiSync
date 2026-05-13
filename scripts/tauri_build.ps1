$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$releaseRoot = Join-Path $frontendRoot "src-tauri\target\release"
$runtimePython = Join-Path $frontendRoot "src-tauri\resources\runtime\python\python.exe"

& (Join-Path $repoRoot "scripts\prepare_tauri_backend.ps1")

if (-not (Test-Path -LiteralPath $runtimePython) -and $env:AISYNC_SKIP_RUNTIME_PREP -ne "1") {
  & (Join-Path $repoRoot "scripts\prepare_runtime_python.ps1")
}

if (Test-Path -LiteralPath $releaseRoot) {
  $resolvedReleaseRoot = (Resolve-Path -LiteralPath $releaseRoot).Path
  @(
    "backend",
    "backend-src",
    "runtime",
    "resources\backend",
    "resources\backend-src",
    "resources\runtime"
  ) | ForEach-Object {
    $target = Join-Path $releaseRoot $_
    $resolvedTarget = Resolve-Path -LiteralPath $target -ErrorAction SilentlyContinue
    if ($resolvedTarget -and $resolvedTarget.Path.StartsWith($resolvedReleaseRoot)) {
      Remove-Item -LiteralPath $resolvedTarget.Path -Recurse -Force
    }
  }
}

Push-Location $frontendRoot
try {
  & npm run build
} finally {
  Pop-Location
}
