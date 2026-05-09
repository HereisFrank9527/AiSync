$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".conda\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
$pyinstallerRoot = Join-Path $backendRoot "build\pyinstaller"
New-Item -ItemType Directory -Force -Path $pyinstallerRoot | Out-Null
$binaryArgs = @()
$condaLibraryBin = Join-Path $repoRoot ".conda\Library\bin"
if (Test-Path $condaLibraryBin) {
  foreach ($name in @("libssl-3-x64.dll", "libcrypto-3-x64.dll")) {
    $path = Join-Path $condaLibraryBin $name
    if (Test-Path $path) {
      $binaryArgs += @("--add-binary", "$path;.")
    }
  }
}

Push-Location $backendRoot
try {
  & $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name aisync-backend `
    --distpath dist `
    --workpath (Join-Path $pyinstallerRoot "work") `
    --specpath $pyinstallerRoot `
    --collect-submodules app `
    @binaryArgs `
    app/cli.py
} finally {
  Pop-Location
}
