param(
  [switch]$AllInstallers,
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

function Add-OldInstallers {
  $bundleRoot = Join-Path $repoRoot "frontend\src-tauri\target\release\bundle"
  if (-not (Test-Path -LiteralPath $bundleRoot)) {
    return
  }
  $installers = Get-ChildItem -LiteralPath $bundleRoot -Recurse -File -Include "*.exe", "*.msi" |
    Sort-Object LastWriteTime -Descending
  if ($AllInstallers) {
    $installers | ForEach-Object { $targets.Add($_.FullName) }
    return
  }
  $latestNsis = $installers | Where-Object { $_.FullName -match "\\nsis\\AiSync_.*-setup\.exe$" } | Select-Object -First 1
  foreach ($item in $installers) {
    if ($item.FullName -match "\\msi\\") {
      continue
    }
    if ($latestNsis -and $item.FullName -eq $latestNsis.FullName) {
      continue
    }
    $targets.Add($item.FullName)
  }
}

Add-Target (Join-Path $repoRoot "frontend\dist")
Add-Target (Join-Path $repoRoot "frontend\src-tauri\target\release\wix")
Add-Target (Join-Path $repoRoot "frontend\src-tauri\target\release\bundle\msi")
Add-Target (Join-Path $repoRoot ".dev-logs")
Add-Target (Join-Path $repoRoot ".runtime-cache")
Get-ChildItem -LiteralPath $repoRoot -File -Filter "*.log" -ErrorAction SilentlyContinue |
  ForEach-Object { $targets.Add($_.FullName) }
Add-OldInstallers

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
