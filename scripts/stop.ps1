<#
.SYNOPSIS
  Stops PARE. Data is kept in Docker volumes and is available on next start.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop
Write-Host "PARE stopped. Your data is preserved." -ForegroundColor Green
Write-Host "To delete ALL data permanently: docker compose down -v"
