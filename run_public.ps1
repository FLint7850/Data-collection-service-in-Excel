$ErrorActionPreference = "Stop"
$Port = 5055
$AppUrl = "http://127.0.0.1:$Port"

function Find-Python {
    $candidates = @(
        @{ Command = "python"; Args = @("--version") },
        @{ Command = "py"; Args = @("-3", "--version") },
        @{ Command = "python3"; Args = @("--version") }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }

        try {
            & $candidate.Command @($candidate.Args) *> $null
            return $candidate.Command
        }
        catch {
            continue
        }
    }

    return $null
}

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri "$AppUrl/api/projects" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ne 200) {
            return $false
        }
        $data = $response.Content | ConvertFrom-Json
        return $null -ne $data.projects
    }
    catch {
        return $false
    }
}

function Test-PortBusy {
    param([int]$PortToCheck)
    try {
        $connection = Get-NetTCPConnection -LocalPort $PortToCheck -ErrorAction SilentlyContinue | Select-Object -First 1
        return $null -ne $connection
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

function Find-XTunnel {
    $localCandidates = @(
        (Join-Path $PSScriptRoot "tools\xtunnel\xtunnel.exe"),
        (Join-Path $PSScriptRoot "xtunnel.exe")
    )

    foreach ($candidate in $localCandidates) {
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

$xtunnelPath = Find-XTunnel
if (-not $xtunnelPath) {
    Write-Host "xTunnel is not installed or is not available in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "Run INSTALL_XTUNNEL.cmd once, or download Windows x64 manually from:" -ForegroundColor Yellow
    Write-Host "https://xtunnel.ru/docs/install/windows/zip"
    Write-Host ""
    Write-Host "Then activate xTunnel once:"
    Write-Host "   .\tools\xtunnel\xtunnel.exe register YOUR_KEY"
    Write-Host ""
    Write-Host "After that run START_PUBLIC_PARSER.cmd again." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Enter to close this window."
    Read-Host
    exit 1
}

Write-Host "Using xTunnel: $xtunnelPath" -ForegroundColor Cyan

$python = Find-Python
if (-not $python) {
    Write-Host "Python was not found in PATH." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'." -ForegroundColor Yellow
    Write-Host "Press Enter to close this window."
    Read-Host
    exit 1
}

if ($python -eq "py") {
    $pythonArgs = @("-3")
}
else {
    $pythonArgs = @()
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    & $python @pythonArgs -m venv .venv
}

$venvPython = Join-Path ".venv" "Scripts\python.exe"

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

Write-Host "Installing Playwright Chromium..." -ForegroundColor Cyan
& $venvPython -m playwright install chromium

Write-Host "Preparing Crawl4AI browsers..." -ForegroundColor Cyan
& $venvPython -m crawl4ai-setup

if (Test-AppReady) {
    Write-Host "The app is already running at $AppUrl" -ForegroundColor Green
}
else {
    if (Test-PortBusy -PortToCheck $Port) {
        for ($candidate = 5056; $candidate -le 5065; $candidate++) {
            if (-not (Test-PortBusy -PortToCheck $candidate)) {
                $Port = $candidate
                $AppUrl = "http://127.0.0.1:$Port"
                Write-Host "Default parser port is busy. Using $AppUrl instead." -ForegroundColor Yellow
                break
            }
        }
    }

    $LogStamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LogDir = Join-Path $PSScriptRoot "logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $AppLog = Join-Path $LogDir "app.log"
    Add-Content -Path $AppLog -Encoding UTF8 -Value ""
    Add-Content -Path $AppLog -Encoding UTF8 -Value "[$(Get-Date -Format o)] Starting public server on port $Port"

    Write-Host "Starting Flask app..." -ForegroundColor Green
    $env:PORT = "$Port"
    $LaunchCommand = "set PORT=$Port&& set PYTHONIOENCODING=utf-8&& `"$venvPython`" `"app.py`" >> `"$AppLog`" 2>>&1"
    $appProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/c", $LaunchCommand `
        -WorkingDirectory $PSScriptRoot `
        -PassThru `
        -WindowStyle Hidden

    Write-Host "Waiting for $AppUrl ..." -ForegroundColor Cyan
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        if ($appProcess.HasExited) {
            break
        }
        if (Test-AppReady) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        Write-Host "The app did not start correctly." -ForegroundColor Red
        if (Test-Path $AppLog) {
            Write-Host ""
            Write-Host "${AppLog}:" -ForegroundColor Yellow
            Get-Content $AppLog -Tail 120
        }
        Stop-StartedProcess $appProcess
        Write-Host "Press Enter to close this window."
        Read-Host
        exit 1
    }
}

Write-Host ""
Write-Host "Local app is ready: $AppUrl" -ForegroundColor Green
Start-Process $AppUrl
Write-Host ""
Write-Host "Starting xTunnel. Copy the public HTTPS URL from the output below and send it to other users." -ForegroundColor Yellow
Write-Host "Keep this window open while the public link is needed." -ForegroundColor Yellow
Write-Host ""

try {
    & $xtunnelPath http $Port --tunnel-host tunnel4.com
}
finally {
    Stop-StartedProcess $appProcess
}
