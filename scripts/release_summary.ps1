$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tauriConfig = Join-Path $repoRoot "frontend\src-tauri\tauri.conf.json"
$resourcesRoot = Join-Path $repoRoot "frontend\src-tauri\resources"
$bundleRoot = Join-Path $repoRoot "frontend\src-tauri\target\release\bundle"
$releaseExe = Join-Path $repoRoot "frontend\src-tauri\target\release\aisync.exe"
$distIndex = Join-Path $repoRoot "frontend\dist\index.html"

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

function Get-FrontendAssetNames {
  if (-not (Test-Path -LiteralPath $distIndex)) {
    return @()
  }
  $html = Get-Content -Raw -Encoding UTF8 -LiteralPath $distIndex
  $matches = [regex]::Matches($html, "assets/[^`"'<>]+\.(?:js|css)")
  return @($matches | ForEach-Object { $_.Value } | Select-Object -Unique)
}

function Test-BinaryContainsText {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Text
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    return $false
  }
  if (-not $Text) {
    return $false
  }
  $binaryText = [System.Text.Encoding]::GetEncoding(28591).GetString([System.IO.File]::ReadAllBytes($Path))
  return $binaryText.Contains($Text)
}

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
Format-FileStatus $releaseExe | Format-List
Format-FileStatus $nsis | Format-List
if (Test-Path -LiteralPath $msi) {
  Write-Host "Optional MSI"
  Format-FileStatus $msi | Format-List
} else {
  Write-Host "Optional MSI: disabled; NSIS is the release artifact."
}
Write-Host "Frontend assets"
$frontendAssets = Get-FrontendAssetNames
if ($frontendAssets.Count -eq 0) {
  Write-Host "No frontend assets found in $distIndex"
} else {
  foreach ($asset in $frontendAssets) {
    $embedded = Test-BinaryContainsText -Path $releaseExe -Text $asset
    [pscustomobject]@{
      Asset = $asset
      EmbeddedInReleaseExe = $embedded
    } | Format-List
  }
}
Write-Host "Runtime"
Format-FileStatus $runtimePython | Format-List
Format-FileStatus $runtimePythonw | Format-List
Format-FileStatus $backendSource | Format-List

if (-not (Test-Path -LiteralPath $releaseExe)) {
  throw "release exe missing: $releaseExe"
}
if (-not (Test-Path -LiteralPath $nsis)) {
  throw "NSIS installer missing: $nsis"
}
if ((Test-Path -LiteralPath $nsis) -and (Test-Path -LiteralPath $releaseExe)) {
  $nsisItem = Get-Item -LiteralPath $nsis
  $releaseItem = Get-Item -LiteralPath $releaseExe
  if ($nsisItem.LastWriteTime -lt $releaseItem.LastWriteTime.AddMinutes(-2)) {
    throw "NSIS installer is older than release exe. Re-run npm run build from repo root."
  }
}
if (-not (Test-Path -LiteralPath $runtimePython)) {
  throw "runtime python missing: $runtimePython"
}
if (-not (Test-Path -LiteralPath $backendSource)) {
  throw "backend source missing: $backendSource"
}
foreach ($asset in $frontendAssets) {
  if (-not (Test-BinaryContainsText -Path $releaseExe -Text $asset)) {
    throw "release exe does not contain current frontend asset: $asset. Run npm run build from repo root and reinstall the newly generated installer."
  }
}
