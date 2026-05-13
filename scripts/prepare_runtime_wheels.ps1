param(
  [string]$Python = "",
  [switch]$IncludeVector
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$runtimeRoot = Join-Path $repoRoot "frontend\src-tauri\resources\runtime"
$wheelDir = Join-Path $runtimeRoot "wheels"

if (-not $Python) {
  $localPython = Join-Path $repoRoot ".conda\python.exe"
  if (Test-Path -LiteralPath $localPython) {
    $Python = $localPython
  } else {
    $Python = "python"
  }
}

$resolvedRuntimeRoot = Resolve-Path -LiteralPath $runtimeRoot -ErrorAction SilentlyContinue
if (-not $resolvedRuntimeRoot) {
  New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
  $resolvedRuntimeRoot = Resolve-Path -LiteralPath $runtimeRoot
}

$resolvedWheelDir = Resolve-Path -LiteralPath $wheelDir -ErrorAction SilentlyContinue
if ($resolvedWheelDir -and $resolvedWheelDir.Path.StartsWith($resolvedRuntimeRoot.Path)) {
  Remove-Item -LiteralPath $resolvedWheelDir.Path -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null

$backendSpec = $backendRoot
if ($IncludeVector) {
  $backendSpec = "$backendRoot[vector]"
}

& $Python -m pip wheel --wheel-dir $wheelDir --no-cache-dir $backendSpec
