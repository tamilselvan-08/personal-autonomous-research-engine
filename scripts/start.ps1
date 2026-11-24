<#
.SYNOPSIS
  Starts PARE with Docker Desktop and opens the dashboard.
.PARAMETER Dev
  Use the hot-reload development stack.
.PARAMETER NoBrowser
  Do not open the browser when ready.
#>
param([switch]$Dev, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running. Start Docker Desktop and wait until it says 'Engine running', then try again." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) { & "$PSScriptRoot\setup-env.ps1" }

$files = @("-f", "docker-compose.yml")
if ($Dev) { $files += @("-f", "docker-compose.dev.yml") }

Write-Host "Building and starting PARE (first run downloads images and can take several minutes)..."
docker compose @files up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "docker compose failed. See the output above." -ForegroundColor Red; exit 1 }

$apiPort = (Select-String -Path .env -Pattern '^API_PORT=(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1
$webPort = (Select-String -Path .env -Pattern '^WEB_PORT=(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1
if (-not $apiPort) { $apiPort = 8000 }
if (-not $webPort) { $webPort = 3000 }

Write-Host "Waiting for the API to become ready..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://localhost:$apiPort/health/ready"
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Host "API did not become ready in 3 minutes. Check logs with: docker compose logs api" -ForegroundColor Red
    exit 1
}

Write-Host "PARE is running:" -ForegroundColor Green
Write-Host "  Dashboard: http://localhost:$webPort"
Write-Host "  API:       http://localhost:$apiPort"
Write-Host "  API docs:  http://localhost:$apiPort/docs"
if (-not $NoBrowser) { Start-Process "http://localhost:$webPort" }
