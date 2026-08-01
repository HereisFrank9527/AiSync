param(
  [switch]$WithChroma
)

$ErrorActionPreference = "Stop"

$packageRoot = $PSScriptRoot
$venvRoot = Join-Path $packageRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"

function Find-Python {
  $candidates = [System.Collections.Generic.List[object]]::new()
  foreach ($name in @("python", "python3")) {
    foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
      $candidates.Add([pscustomobject]@{
        Executable = $command.Source
        PrefixArguments = @()
      })
    }
  }

  foreach ($command in @(Get-Command "py" -All -ErrorAction SilentlyContinue)) {
    $candidates.Add([pscustomobject]@{
      Executable = $command.Source
      PrefixArguments = @("-3")
    })
  }

  $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($candidate in $candidates) {
    $key = "$($candidate.Executable)|$($candidate.PrefixArguments -join ' ')"
    if (-not $seen.Add($key)) {
      continue
    }
    $probeArguments = @($candidate.PrefixArguments) + @(
      "-c",
      "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    )
    try {
      $versionText = (& $candidate.Executable @probeArguments 2>$null | Select-Object -Last 1)
    } catch {
      continue
    }
    if ($versionText) {
      try {
        if ([version]$versionText -ge [version]"3.11") {
          return $candidate
        }
      } catch {
        continue
      }
    }
  }
  throw "Python 3.11 or newer was not found. Install Python and enable Add Python to PATH."
}

if (-not (Test-Path -LiteralPath $venvPython)) {
  $systemPython = Find-Python
  $venvArguments = @($systemPython.PrefixArguments) + @("-m", "venv", $venvRoot)
  Write-Host "Creating local Python environment..."
  & $systemPython.Executable @venvArguments
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create the local Python environment."
  }
}

$installTarget = Join-Path $packageRoot "backend"
if ($WithChroma) {
  $installTarget = "$installTarget[vector]"
}

Write-Host "Installing AiSync backend dependencies..."
& $venvPython -m pip install -e $installTarget
if ($LASTEXITCODE -ne 0) {
  throw "Failed to install AiSync backend dependencies."
}

Write-Host "AiSync setup complete." -ForegroundColor Green
