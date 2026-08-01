$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$backendRoot = Join-Path $repoRoot "backend"
$backendPort = if ($env:AISYNC_BACKEND_PORT) { $env:AISYNC_BACKEND_PORT } else { "27631" }
$frontendPort = if ($env:AISYNC_FRONTEND_PORT) { $env:AISYNC_FRONTEND_PORT } else { "1420" }
$python = Join-Path $repoRoot ".conda\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$logDir = Join-Path $repoRoot ".dev-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-LanAddress {
  $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.PrefixOrigin -ne "WellKnown"
    } |
    Select-Object -ExpandProperty IPAddress)
  if ($addresses) {
    return $addresses[0]
  }
  return "YOUR-LAN-IP"
}

function Test-BackendHealth {
  try {
    $response = Invoke-RestMethod "http://127.0.0.1:$backendPort/health" -TimeoutSec 2
    return $response.status -eq "ok"
  } catch {
    return $false
  }
}

function Write-BackendLogTail {
  param(
    [string]$StandardOutputPath,
    [string]$StandardErrorPath
  )

  foreach ($logPath in @($StandardErrorPath, $StandardOutputPath)) {
    if (-not (Test-Path -LiteralPath $logPath)) {
      continue
    }
    $lines = @(Get-Content -LiteralPath $logPath -Tail 30 -ErrorAction SilentlyContinue)
    if ($lines.Count -eq 0) {
      continue
    }
    Write-Host "--- $logPath ---" -ForegroundColor DarkYellow
    $lines | ForEach-Object { Write-Host $_ }
  }
}

function Get-DescendantProcessIds {
  param([int]$RootProcessId)

  $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $pending = [System.Collections.Generic.Queue[int]]::new()
  $descendants = [System.Collections.Generic.List[int]]::new()
  $pending.Enqueue($RootProcessId)
  while ($pending.Count -gt 0) {
    $parentId = $pending.Dequeue()
    foreach ($process in $processes | Where-Object { $_.ParentProcessId -eq $parentId }) {
      $childId = [int]$process.ProcessId
      $descendants.Add($childId)
      $pending.Enqueue($childId)
    }
  }
  return $descendants.ToArray()
}

function Stop-ManagedProcessTree {
  param([int]$RootProcessId)

  $descendants = @(Get-DescendantProcessIds -RootProcessId $RootProcessId)
  for ($index = $descendants.Count - 1; $index -ge 0; $index -= 1) {
    Stop-Process -Id $descendants[$index] -Force -ErrorAction SilentlyContinue
  }
  Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
}

function Remove-OrphanedBackend {
  $portNumber = 0
  if (-not [int]::TryParse($backendPort, [ref]$portNumber)) {
    return
  }
  $listeners = @(Get-NetTCPConnection -LocalPort $portNumber -State Listen -ErrorAction SilentlyContinue)
  foreach ($listener in $listeners) {
    $ownerId = [int]$listener.OwningProcess
    if (Get-Process -Id $ownerId -ErrorAction SilentlyContinue) {
      continue
    }

    $orphanedChildren = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.ParentProcessId -eq $ownerId -and
        $_.Name -eq "python.exe" -and
        $_.ExecutablePath -eq $python
      })
    foreach ($process in $orphanedChildren) {
      Write-Host "Removing stale AiSync backend process $($process.ProcessId)..." -ForegroundColor Yellow
      Stop-ManagedProcessTree -RootProcessId ([int]$process.ProcessId)
    }
  }
}

function Wait-BackendReady {
  param(
    [System.Diagnostics.Process]$Process,
    [string]$StandardOutputPath,
    [string]$StandardErrorPath,
    [int]$TimeoutSeconds = 60
  )

  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  Write-Host "Waiting for backend health check..." -NoNewline
  while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    if (Test-BackendHealth) {
      Write-Host " ready ($([math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s)" -ForegroundColor Green
      return
    }

    $Process.Refresh()
    if ($Process.HasExited) {
      $Process.WaitForExit()
      Write-Host " failed" -ForegroundColor Red
      Write-BackendLogTail -StandardOutputPath $StandardOutputPath -StandardErrorPath $StandardErrorPath
      $exitCode = $Process.ExitCode
      $exitDetail = if ($null -eq $exitCode) { "" } else { " (exit code $exitCode)" }
      throw "Backend exited before becoming ready$exitDetail."
    }
    Start-Sleep -Milliseconds 500
  }

  Write-Host " timed out" -ForegroundColor Red
  Write-BackendLogTail -StandardOutputPath $StandardOutputPath -StandardErrorPath $StandardErrorPath
  Stop-ManagedProcessTree -RootProcessId $Process.Id
  throw "Backend health check timed out after $TimeoutSeconds seconds."
}

$lanIp = Get-LanAddress
Write-Host "AiSync LAN dev mode"
Write-Host "Frontend: http://$lanIp`:$frontendPort"
Write-Host "Backend:  http://$lanIp`:$backendPort"
Write-Host "Warning: LAN mode has no login/auth. Use only on trusted networks."
Write-Host "Press Ctrl+C to stop."

Remove-OrphanedBackend
$backendProcess = $null
if (-not (Test-BackendHealth)) {
  $backendOut = Join-Path $logDir "backend-lan.out.log"
  $backendErr = Join-Path $logDir "backend-lan.err.log"
  $backendProcess = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "app.cli", "--host", "0.0.0.0", "--port", $backendPort, "--reload") `
    -WorkingDirectory $backendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru
  Wait-BackendReady `
    -Process $backendProcess `
    -StandardOutputPath $backendOut `
    -StandardErrorPath $backendErr
} else {
  Write-Host "Backend health check passed (reusing the running service)." -ForegroundColor Green
}

Push-Location $frontendRoot
try {
  $env:AISYNC_VITE_HOST = "0.0.0.0"
  $env:AISYNC_BACKEND_PORT = $backendPort
  $env:VITE_API_BASE = "/api"
  & npm run dev -- --host 0.0.0.0 --port $frontendPort
} finally {
  Pop-Location
  if ($backendProcess) {
    Stop-ManagedProcessTree -RootProcessId $backendProcess.Id
  }
}
