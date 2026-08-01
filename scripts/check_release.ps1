param(
  [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$rootPackagePath = Join-Path $repoRoot "package.json"
$frontendPackagePath = Join-Path $repoRoot "frontend\package.json"
$backendProjectPath = Join-Path $repoRoot "backend\pyproject.toml"

$rootPackage = Get-Content -LiteralPath $rootPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
$frontendPackage = Get-Content -LiteralPath $frontendPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
$backendProject = Get-Content -LiteralPath $backendProjectPath -Raw -Encoding UTF8
$backendVersionMatch = [regex]::Match(
  $backendProject,
  '(?m)^version\s*=\s*"(?<version>[^"]+)"\s*$'
)

if (-not $backendVersionMatch.Success) {
  throw "Unable to read backend version from backend/pyproject.toml."
}

$versions = [ordered]@{
  root = [string]$rootPackage.version
  frontend = [string]$frontendPackage.version
  backend = $backendVersionMatch.Groups["version"].Value
}
$uniqueVersions = @($versions.Values | Sort-Object -Unique)
if ($uniqueVersions.Count -ne 1) {
  $detail = ($versions.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ", "
  throw "AiSync versions are inconsistent: $detail"
}

$version = $uniqueVersions[0]
if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
  throw "AiSync version is not valid SemVer: $version"
}

if ($ExpectedVersion) {
  $normalizedExpected = $ExpectedVersion.Trim()
  if ($normalizedExpected.StartsWith("v")) {
    $normalizedExpected = $normalizedExpected.Substring(1)
  }
  if ($normalizedExpected -ne $version) {
    throw "Expected version $normalizedExpected, but repository version is $version."
  }
}

if ($backendProject -match '(?i)pyinstaller') {
  throw "backend/pyproject.toml still contains a PyInstaller dependency."
}

foreach ($legacyPath in @("frontend\src-tauri", "src-tauri")) {
  if (Test-Path -LiteralPath (Join-Path $repoRoot $legacyPath)) {
    throw "Legacy desktop path still exists: $legacyPath"
  }
}

Write-Host "AiSync release metadata is consistent: v$version" -ForegroundColor Green
