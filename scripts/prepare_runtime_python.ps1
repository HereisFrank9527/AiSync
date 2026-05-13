param(
  [string]$PythonVersion = "3.11.9",
  [string]$PythonUrl = "",
  [string]$BuildPython = "",
  [switch]$IncludeVector
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$tauriResourceRoot = Join-Path $repoRoot "frontend\src-tauri\resources"
$runtimeRoot = Join-Path $tauriResourceRoot "runtime"
$pythonDir = Join-Path $runtimeRoot "python"
$cacheRoot = Join-Path $repoRoot ".runtime-cache"

function Remove-PythonCaches {
  param(
    [Parameter(Mandatory = $true)][string]$Root
  )

  Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
  Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -Filter "__pycache__" |
    Sort-Object FullName -Descending |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

if (-not $PythonUrl) {
  $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
}

if (-not $BuildPython) {
  $localPython = Join-Path $repoRoot ".conda\python.exe"
  if (Test-Path -LiteralPath $localPython) {
    $BuildPython = $localPython
  } else {
    $BuildPython = "python"
  }
}

$resolvedResourceRoot = Resolve-Path -LiteralPath $tauriResourceRoot -ErrorAction SilentlyContinue
if (-not $resolvedResourceRoot) {
  New-Item -ItemType Directory -Force -Path $tauriResourceRoot | Out-Null
  $resolvedResourceRoot = Resolve-Path -LiteralPath $tauriResourceRoot
}
New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null

$resolvedPythonDir = Resolve-Path -LiteralPath $pythonDir -ErrorAction SilentlyContinue
if ($resolvedPythonDir -and $resolvedPythonDir.Path.StartsWith($resolvedResourceRoot.Path)) {
  $oldPythonDir = Join-Path $cacheRoot ("python-old-" + [Guid]::NewGuid().ToString("N"))
  Move-Item -LiteralPath $resolvedPythonDir.Path -Destination $oldPythonDir -Force
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
      Remove-Item -LiteralPath $oldPythonDir -Recurse -Force -ErrorAction Stop
      break
    } catch {
      if ($attempt -eq 3) {
        Write-Warning "Failed to remove old runtime cache: $oldPythonDir"
      } else {
        Start-Sleep -Milliseconds 300
      }
    }
  }
}

New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null

$zipPath = Join-Path $cacheRoot ("python-$PythonVersion-embed-amd64.zip")
if (-not (Test-Path -LiteralPath $zipPath)) {
  Invoke-WebRequest -Uri $PythonUrl -OutFile $zipPath
}

Expand-Archive -LiteralPath $zipPath -DestinationPath $pythonDir -Force

$pthFile = Get-ChildItem -LiteralPath $pythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $pthFile) {
  throw "Embeddable Python _pth file not found in $pythonDir"
}

$pthLines = Get-Content -LiteralPath $pthFile.FullName -Encoding UTF8
$newLines = New-Object System.Collections.Generic.List[string]
$hasSitePackages = $false
$hasImportSite = $false
foreach ($line in $pthLines) {
  if ($line.Trim() -eq "Lib\site-packages") {
    $hasSitePackages = $true
  }
  if ($line.Trim() -eq "import site" -or $line.Trim() -eq "#import site") {
    if (-not $hasImportSite) {
      $newLines.Add("import site")
      $hasImportSite = $true
    }
  } else {
    $newLines.Add($line)
  }
}
if (-not $hasSitePackages) {
  $newLines.Insert([Math]::Max(0, $newLines.Count - 1), "Lib\site-packages")
}
if (-not $hasImportSite) {
  $newLines.Add("import site")
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($pthFile.FullName, [string[]]$newLines, $utf8NoBom)

$sitePackages = Join-Path $pythonDir "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

$backendSpec = $backendRoot
if ($IncludeVector) {
  $backendSpec = "$backendRoot[vector]"
}

& $BuildPython -m pip install --upgrade --no-compile --target $sitePackages $backendSpec

$scriptBin = Join-Path $sitePackages "bin"
if (Test-Path -LiteralPath $scriptBin) {
  Remove-Item -LiteralPath $scriptBin -Recurse -Force
}
Remove-PythonCaches -Root $pythonDir

$testScript = "import fastapi, uvicorn, app.cli; print('runtime python ok')"
$env:PYTHONDONTWRITEBYTECODE = "1"
try {
  & (Join-Path $pythonDir "python.exe") -c $testScript
} finally {
  Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
}
Remove-PythonCaches -Root $pythonDir
