param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targets = New-Object System.Collections.Generic.List[string]

function Add-Target {
  param([string]$Path)
  if (Test-Path -LiteralPath $Path) {
    $targets.Add((Resolve-Path -LiteralPath $Path).Path)
  }
}

Add-Target (Join-Path $repoRoot "frontend\dist")
Add-Target (Join-Path $repoRoot ".dev-logs")
Add-Target (Join-Path $repoRoot ".runtime-cache")
Get-ChildItem -LiteralPath $repoRoot -File -Filter "*.log" -ErrorAction SilentlyContinue |
  ForEach-Object { $targets.Add($_.FullName) }

$workspace = (Resolve-Path -LiteralPath $repoRoot).Path
$uniqueTargets = $targets | Sort-Object -Unique

foreach ($target in $uniqueTargets) {
  if (-not $target.StartsWith($workspace)) {
    throw "Refusing to remove path outside workspace: $target"
  }
}

if ($uniqueTargets.Count -eq 0) {
  Write-Host "No build artifacts to clean."
  exit 0
}

Write-Host "Build artifacts to clean:"
$uniqueTargets | ForEach-Object { Write-Host "  $_" }

if ($DryRun) {
  Write-Host "DryRun enabled; no files removed."
  exit 0
}

foreach ($target in $uniqueTargets) {
  Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Clean complete."
