param(
  [string]$OutputRoot = "",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$checkScript = Join-Path $PSScriptRoot "check_release.ps1"
& $checkScript

$rootPackage = Get-Content -LiteralPath (Join-Path $repoRoot "package.json") -Raw -Encoding UTF8 |
  ConvertFrom-Json
$version = [string]$rootPackage.version

if (-not $SkipBuild) {
  Push-Location $repoRoot
  try {
    & npm run build
    if ($LASTEXITCODE -ne 0) {
      throw "Frontend production build failed."
    }
  } finally {
    Pop-Location
  }
}

$frontendDist = Join-Path $repoRoot "frontend\dist"
if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
  throw "frontend/dist/index.html is missing. Run npm run build first."
}

if (-not $OutputRoot) {
  $OutputRoot = Join-Path $repoRoot ".release"
}
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$resolvedOutputRoot = (Resolve-Path -LiteralPath $OutputRoot).Path
$packageName = "AiSync-web-v$version"
$stagingRoot = Join-Path $resolvedOutputRoot $packageName
$zipPath = Join-Path $resolvedOutputRoot "$packageName.zip"
$hashPath = "$zipPath.sha256"

foreach ($target in @($stagingRoot, $zipPath, $hashPath)) {
  $fullTarget = [System.IO.Path]::GetFullPath($target)
  if (-not $fullTarget.StartsWith($resolvedOutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to replace a path outside the release directory: $fullTarget"
  }
  if (Test-Path -LiteralPath $fullTarget) {
    Remove-Item -LiteralPath $fullTarget -Recurse -Force
  }
}

New-Item -ItemType Directory -Force -Path (Join-Path $stagingRoot "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stagingRoot "frontend") | Out-Null

Copy-Item -LiteralPath (Join-Path $repoRoot "backend\app") -Destination (Join-Path $stagingRoot "backend\app") -Recurse
Copy-Item -LiteralPath (Join-Path $repoRoot "backend\pyproject.toml") -Destination (Join-Path $stagingRoot "backend\pyproject.toml")
Copy-Item -LiteralPath (Join-Path $repoRoot "backend\.env.example") -Destination (Join-Path $stagingRoot "backend\.env.example")
Copy-Item -LiteralPath $frontendDist -Destination (Join-Path $stagingRoot "frontend\dist") -Recurse
Copy-Item -LiteralPath (Join-Path $repoRoot "packaging\web\setup.ps1") -Destination (Join-Path $stagingRoot "setup.ps1")
Copy-Item -LiteralPath (Join-Path $repoRoot "packaging\web\start.ps1") -Destination (Join-Path $stagingRoot "start.ps1")
Copy-Item -LiteralPath (Join-Path $repoRoot "packaging\web\README.md") -Destination (Join-Path $stagingRoot "README.md")
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination (Join-Path $stagingRoot "LICENSE")
Copy-Item -LiteralPath (Join-Path $repoRoot "CHANGELOG.md") -Destination (Join-Path $stagingRoot "CHANGELOG.md")
Set-Content -LiteralPath (Join-Path $stagingRoot "VERSION") -Value $version -Encoding ASCII

Get-ChildItem -LiteralPath $stagingRoot -Directory -Recurse -Force |
  Where-Object { $_.Name -eq "__pycache__" } |
  Sort-Object { $_.FullName.Length } -Descending |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Get-ChildItem -LiteralPath $stagingRoot -File -Recurse -Force |
  Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
  $stagingRoot,
  $zipPath,
  [System.IO.Compression.CompressionLevel]::Optimal,
  $true
)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$zipStream = [System.IO.File]::OpenRead($zipPath)
try {
  $hashBytes = $sha256.ComputeHash($zipStream)
} finally {
  $zipStream.Dispose()
  $sha256.Dispose()
}
$hash = ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToLowerInvariant()
Set-Content -LiteralPath $hashPath -Value "$hash  $([System.IO.Path]::GetFileName($zipPath))" -Encoding ASCII

$zip = Get-Item -LiteralPath $zipPath
Write-Host "Web release package created:" -ForegroundColor Green
Write-Host "  $($zip.FullName)"
Write-Host "  size=$($zip.Length) bytes"
Write-Host "  sha256=$hash"
