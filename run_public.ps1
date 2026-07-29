$ErrorActionPreference = "Stop"

$BackendPort = 5055
$FrontendPort = 3000
$FrontendDir = Join-Path $PSScriptRoot "frontend"

function Load-LocalEnv {
    $envPath = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envPath)) {
        return
    }
    foreach ($rawLine in Get-Content -Encoding UTF8 -LiteralPath $envPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Find-Python {
    foreach ($candidate in @("python", "py", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }
    return $null
}

function Find-XTunnel {
    foreach ($candidate in @(
        (Join-Path $PSScriptRoot "tools\xtunnel\xtunnel.exe"),
        (Join-Path $PSScriptRoot "xtunnel.exe")
    )) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $command = Get-Command xtunnel -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

function Test-PortBusy {
    param([int]$PortToCheck)
    try {
        return $null -ne (Get-NetTCPConnection -LocalPort $PortToCheck -ErrorAction SilentlyContinue | Select-Object -First 1)
    }
    catch {
        return $false
    }
}

function Find-FreePort {
    param([int]$Preferred, [int]$Last)
    for ($candidate = $Preferred; $candidate -le $Last; $candidate++) {
        if (-not (Test-PortBusy -PortToCheck $candidate)) {
            return $candidate
        }
    }
    throw "No free port found in range $Preferred-$Last."
}

function Test-JsonHealth {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and ($response.Content | ConvertFrom-Json).ok -eq $true
    }
    catch {
        return $false
    }
}

function Stop-StartedProcess {
    param($Process)
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

Load-LocalEnv

$xtunnelPath = Find-XTunnel
if (-not $xtunnelPath) {
    Write-Host "xTunnel is not installed or is not available in PATH." -ForegroundColor Red
    Write-Host "Run INSTALL_XTUNNEL.cmd, activate xTunnel, then try again." -ForegroundColor Yellow
    Write-Host "Press Enter to close this window."
    Read-Host
    exit 1
}

$python = Find-Python
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $python -or -not $nodeCommand -or -not $npmCommand) {
    Write-Host "Python 3.10+ and Node.js 20+ are required." -ForegroundColor Red
    Write-Host "Press Enter to close this window."
    Read-Host
    exit 1
}

$pythonArgs = if ($python -eq "py") { @("-3") } else { @() }
$createdVenv = $false
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python environment..." -ForegroundColor Cyan
    & $python @pythonArgs -m venv .venv
    $createdVenv = $true
}

$venvPython = Join-Path ".venv" "Scripts\python.exe"
$ForceBrowserSetup = $env:FORCE_BROWSER_SETUP -eq "1"

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

if ($createdVenv -or $ForceBrowserSetup) {
    & $venvPython -m playwright install chromium chromium-headless-shell
    $crawl4aiSetup = Join-Path ".venv" "Scripts\crawl4ai-setup.exe"
    if (Test-Path $crawl4aiSetup) {
        & $crawl4aiSetup
    }
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules\.bin\nuxt.cmd"))) {
    Push-Location $FrontendDir
    try {
        & $($npmCommand.Source) ci
    }
    finally {
        Pop-Location
    }
}

$BackendPort = Find-FreePort -Preferred $BackendPort -Last 5065
$FrontendPort = Find-FreePort -Preferred $FrontendPort -Last 3010
$BackendUrl = "http://127.0.0.1:$BackendPort"
$AppUrl = "http://127.0.0.1:$FrontendPort"

$LogDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BackendLog = Join-Path $LogDir "backend.log"
$FrontendLog = Join-Path $LogDir "frontend.log"
$backendProcess = $null
$frontendProcess = $null

try {
    Write-Host "Starting API at $BackendUrl ..." -ForegroundColor Green
    $backendCommand = "set PORT=$BackendPort&& set PYTHONIOENCODING=utf-8&& `"$venvPython`" `"app.py`" >> `"$BackendLog`" 2>>&1"
    $backendProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/c", $backendCommand `
        -WorkingDirectory $PSScriptRoot `
        -PassThru `
        -WindowStyle Hidden

    $backendReady = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-JsonHealth -Url $BackendUrl) {
            $backendReady = $true
            break
        }
        if ($backendProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $backendReady) {
        throw "The API did not start. Check $BackendLog."
    }

    Write-Host "Starting Nuxt at $AppUrl ..." -ForegroundColor Green
    $frontendCommand = "set PORT=$FrontendPort&& set NUXT_BACKEND_URL=$BackendUrl&& `"$($npmCommand.Source)`" run dev -- --host 127.0.0.1 --port $FrontendPort >> `"$FrontendLog`" 2>>&1"
    $frontendProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/c", $frontendCommand `
        -WorkingDirectory $FrontendDir `
        -PassThru `
        -WindowStyle Hidden

    $frontendReady = $false
    for ($i = 0; $i -lt 80; $i++) {
        if (Test-JsonHealth -Url $AppUrl) {
            $frontendReady = $true
            break
        }
        if ($frontendProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $frontendReady) {
        throw "Nuxt did not start. Check $FrontendLog."
    }

    Write-Host "Local application is ready: $AppUrl" -ForegroundColor Green
    Start-Process $AppUrl
    Write-Host ""
    Write-Host "Starting xTunnel for the Nuxt interface." -ForegroundColor Yellow
    Write-Host "Copy the public HTTPS URL and keep this window open." -ForegroundColor Yellow
    Write-Host ""
    & $xtunnelPath http $FrontendPort --tunnel-host tunnel4.com
}
finally {
    Stop-StartedProcess $frontendProcess
    Stop-StartedProcess $backendProcess
}
