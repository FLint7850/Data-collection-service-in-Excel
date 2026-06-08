param(
    [string]$Key = ""
)

$ErrorActionPreference = "Stop"

$DownloadUrl = "https://dl.xtunnel.ru/v2.5.1/xtunnel-v2.5.1-win-x64.zip"
$ToolsDir = Join-Path $PSScriptRoot "tools"
$InstallDir = Join-Path $ToolsDir "xtunnel"
$ZipPath = Join-Path $ToolsDir "xtunnel-win-x64.zip"
$ExePath = Join-Path $InstallDir "xtunnel.exe"

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "Downloading xTunnel Windows x64..." -ForegroundColor Cyan
Write-Host $DownloadUrl
Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath -UseBasicParsing

Write-Host "Extracting xTunnel..." -ForegroundColor Cyan
Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force

$foundExe = Get-ChildItem -Path $InstallDir -Recurse -Filter "xtunnel.exe" | Select-Object -First 1
if (-not $foundExe) {
    throw "xtunnel.exe was not found after extraction."
}

if ($foundExe.FullName -ne $ExePath) {
    Copy-Item -Path $foundExe.FullName -Destination $ExePath -Force
}

Write-Host ""
Write-Host "xTunnel installed locally:" -ForegroundColor Green
Write-Host $ExePath
Write-Host ""

Write-Host "Checking version..." -ForegroundColor Cyan
& $ExePath version

Write-Host ""
Write-Host "Now activate xTunnel with your key." -ForegroundColor Yellow
Write-Host "You can paste the key here. It will not be saved in project files."
if (-not $Key) {
    $Key = Read-Host "xTunnel key"
}

if ($Key -and $Key.Trim()) {
    & $ExePath register $Key.Trim()
    Write-Host ""
    Write-Host "Activation command completed." -ForegroundColor Green
}
else {
    Write-Host "Activation skipped. You can run it later:" -ForegroundColor Yellow
    Write-Host ".\tools\xtunnel\xtunnel.exe register YOUR_KEY"
}
