$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$resourceDir = Join-Path $repoRoot "frontend\src-tauri\resources\backend-src"

$resolvedResourcesRoot = Resolve-Path -LiteralPath (Join-Path $repoRoot "frontend\src-tauri\resources") -ErrorAction SilentlyContinue
if (-not $resolvedResourcesRoot) {
  New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot "frontend\src-tauri\resources") | Out-Null
  $resolvedResourcesRoot = Resolve-Path -LiteralPath (Join-Path $repoRoot "frontend\src-tauri\resources")
}

$resolvedResourceDir = Resolve-Path -LiteralPath $resourceDir -ErrorAction SilentlyContinue
if ($resolvedResourceDir -and $resolvedResourceDir.Path.StartsWith($resolvedResourcesRoot.Path)) {
  Remove-Item -LiteralPath $resolvedResourceDir.Path -Recurse -Force
}

function Copy-CleanTree {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  $sourcePath = (Resolve-Path -LiteralPath $Source).Path
  Get-ChildItem -LiteralPath $sourcePath -Recurse -Force |
    Where-Object {
      $_.FullName -notmatch "\\__pycache__(\\|$)" -and
      $_.Extension -notin @(".pyc", ".pyo")
    } |
    ForEach-Object {
      $relativePath = $_.FullName.Substring($sourcePath.Length).TrimStart("\", "/")
      $targetPath = Join-Path $Destination $relativePath
      if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
      } else {
        $targetParent = Split-Path -Parent $targetPath
        New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $targetPath -Force
      }
    }
}

New-Item -ItemType Directory -Force -Path $resourceDir | Out-Null
Copy-CleanTree -Source (Join-Path $backendRoot "app") -Destination (Join-Path $resourceDir "app")
Copy-Item -LiteralPath (Join-Path $backendRoot "pyproject.toml") -Destination (Join-Path $resourceDir "pyproject.toml") -Force
