$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tauriConfig = Join-Path $repoRoot "frontend\src-tauri\tauri.conf.json"
$resourcesRoot = Join-Path $repoRoot "frontend\src-tauri\resources"
$bundleRoot = Join-Path $repoRoot "frontend\src-tauri\target\release\bundle"

if (-not (Test-Path -LiteralPath $tauriConfig)) {
  throw "tauri.conf.json not found: $tauriConfig"
}

$config = Get-Content -Raw -Encoding UTF8 -LiteralPath $tauriConfig | ConvertFrom-Json
$version = [string]$config.version

$nsis = Join-Path $bundleRoot "nsis\AiSync_${version}_x64-setup.exe"
$msi = Join-Path $bundleRoot "msi\AiSync_${version}_x64_en-US.msi"
$runtimePython = Join-Path $resourcesRoot "runtime\python\python.exe"
$runtimePythonw = Join-Path $resourcesRoot "runtime\python\pythonw.exe"
$backendSource = Join-Path $resourcesRoot "backend-src\app\cli.py"

function Format-FileStatus {
  param([string]$Path)
  if (Test-Path -LiteralPath $Path) {
    $item = Get-Item -LiteralPath $Path
    $hash = if (-not $item.PSIsContainer) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash } else { "" }
    [pscustomobject]@{
      Path = $Path
      Exists = $true
      Length = if ($item.PSIsContainer) { $null } else { $item.Length }
      LastWriteTime = $item.LastWriteTime
      Sha256 = $hash
    }
  } else {
    [pscustomobject]@{
      Path = $Path
      Exists = $false
      Length = $null
      LastWriteTime = $null
      Sha256 = ""
    }
  }
}

Write-Host "AiSync release summary"
Write-Host "version=$version"
Write-Host "repo=$repoRoot"
Write-Host ""
Write-Host "Artifacts"
Format-FileStatus $nsis | Format-List
Format-FileStatus $msi | Format-List
Write-Host "Runtime"
Format-FileStatus $runtimePython | Format-List
Format-FileStatus $runtimePythonw | Format-List
Format-FileStatus $backendSource | Format-List

if (-not (Test-Path -LiteralPath $nsis)) {
  throw "NSIS installer missing: $nsis"
}
if (-not (Test-Path -LiteralPath $runtimePython)) {
  throw "runtime python missing: $runtimePython"
}
if (-not (Test-Path -LiteralPath $backendSource)) {
  throw "backend source missing: $backendSource"
}
