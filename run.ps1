$ErrorActionPreference = "Stop"
$Port = 5055
$AppUrl = "http://127.0.0.1:$Port"

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
        if ($key -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

Load-LocalEnv

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

$python = Find-Python

if (-not $python) {
    Write-Host "Python was not found in PATH." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'." -ForegroundColor Yellow
    Write-Host "Then close PowerShell, open it again, and run: .\run.ps1" -ForegroundColor Yellow
    exit 1
}

if ($python -eq "py") {
    $pythonArgs = @("-3")
}
else {
    $pythonArgs = @()
}

$createdVenv = $false
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    & $python @pythonArgs -m venv .venv
    $createdVenv = $true
}

$venvPython = Join-Path ".venv" "Scripts\python.exe"
$ForceBrowserSetup = $env:FORCE_BROWSER_SETUP -eq "1"

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip

Write-Host "Installing dependencies..." -ForegroundColor Cyan
$env:STATIC_DEPS = "true"
& $venvPython -m pip install -r requirements.txt

if ($createdVenv -or $ForceBrowserSetup) {
    Write-Host "Installing Playwright Chromium..." -ForegroundColor Cyan
    & $venvPython -m playwright install chromium
}
else {
    Write-Host "Skipping browser setup for existing .venv. Set FORCE_BROWSER_SETUP=1 to reinstall." -ForegroundColor DarkGray
}

if ($createdVenv -or $ForceBrowserSetup) {
    Write-Host "Preparing Crawl4AI browsers..." -ForegroundColor Cyan
    $crawl4aiSetup = Join-Path ".venv" "Scripts\crawl4ai-setup.exe"
    if (-not (Test-Path $crawl4aiSetup)) {
        Write-Host "crawl4ai-setup.exe was not found. Updating Crawl4AI..." -ForegroundColor Yellow
        & $venvPython -m pip install -U crawl4ai
    }
    if (Test-Path $crawl4aiSetup) {
        & $crawl4aiSetup
    }
    else {
        Write-Host "crawl4ai-setup.exe is still missing after install. Skipping Crawl4AI browser preparation." -ForegroundColor Yellow
    }
}

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri "$AppUrl/api/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ne 200) {
            return $false
        }
        $data = $response.Content | ConvertFrom-Json
        return $data.ok -eq $true
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

if (Test-AppReady) {
    Write-Host "The app is already running at $AppUrl" -ForegroundColor Green
    Start-Process $AppUrl
    Write-Host "Press Enter to close this window." -ForegroundColor Yellow
    Read-Host
    exit 0
}

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
$OutputLogDir = Join-Path $LogDir "server-output"
$ErrorLogDir = Join-Path $LogDir "server-error"
New-Item -ItemType Directory -Force -Path $OutputLogDir, $ErrorLogDir | Out-Null
$OutputLog = Join-Path $OutputLogDir "server-output-$Port-$LogStamp.log"
$ErrorLog = Join-Path $ErrorLogDir "server-error-$Port-$LogStamp.log"

Write-Host "Starting Flask app..." -ForegroundColor Green
$env:PORT = "$Port"
$process = Start-Process `
    -FilePath $venvPython `
    -ArgumentList "app.py" `
    -WorkingDirectory $PSScriptRoot `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutputLog `
    -RedirectStandardError $ErrorLog

Write-Host "Waiting for $AppUrl ..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if ($process.HasExited) {
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
    if (Test-Path $ErrorLog) {
        Write-Host ""
        Write-Host "${ErrorLog}:" -ForegroundColor Yellow
        Get-Content $ErrorLog -Tail 120
    }
    if (Test-Path $OutputLog) {
        Write-Host ""
        Write-Host "${OutputLog}:" -ForegroundColor Yellow
        Get-Content $OutputLog -Tail 120
    }
    Write-Host ""
    Write-Host "Press Enter to close this window." -ForegroundColor Yellow
    Read-Host
    exit 1
}

Write-Host "App is ready: $AppUrl" -ForegroundColor Green
Start-Process $AppUrl
Write-Host ""
Write-Host "Keep this window open while using the app." -ForegroundColor Yellow
Write-Host "Press Enter here to stop the local server." -ForegroundColor Yellow
Read-Host

try {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
catch {
}
