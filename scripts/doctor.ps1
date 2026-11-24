<#
.SYNOPSIS
  Checks this Windows machine for common problems running PARE.
#>
$ok = $true
function Check($label, [scriptblock]$test, $fix) {
    try { $result = & $test } catch { $result = $false }
    if ($result) { Write-Host "[ OK ] $label" -ForegroundColor Green }
    else { Write-Host "[FAIL] $label`n       $fix" -ForegroundColor Red; $script:ok = $false }
}

$os = Get-CimInstance Win32_OperatingSystem
Write-Host "Windows: $($os.Caption) build $($os.BuildNumber)"
Check "Windows 11, or Windows 10 22H2 (build 19045+)" { [int]$os.BuildNumber -ge 19045 } "Update Windows. Windows 10 is best-effort only."

$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
Check "At least 8 GB RAM (found $ramGb GB)" { $ramGb -ge 7.5 } "PARE may run slowly. 16 GB is recommended."

$drive = Get-PSDrive -Name (Get-Location).Drive.Name
$freeGb = [math]::Round($drive.Free / 1GB, 1)
Check "At least 20 GB free disk on $($drive.Name): (found $freeGb GB)" { $freeGb -ge 20 } "Free up disk space."

Check "WSL is installed" { (wsl --status 2>$null) -ne $null } "Run 'wsl --install' in an administrator PowerShell, then reboot."
Check "Docker CLI is installed" { Get-Command docker -ErrorAction Stop } "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
Check "Docker engine is running" { docker info *> $null; $LASTEXITCODE -eq 0 } "Start Docker Desktop and wait for 'Engine running'."
Check "Docker Compose v2 is available" { docker compose version *> $null; $LASTEXITCODE -eq 0 } "Update Docker Desktop."

foreach ($port in 3000, 8000) {
    Check "Port $port is free (or used by PARE)" {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        -not $c -or ((docker compose ps --format '{{.Ports}}' 2>$null) -match ":$port->")
    } "Another program uses port $port. Stop it, or change WEB_PORT/API_PORT in .env."
}

Check ".env exists" { Test-Path (Join-Path (Split-Path -Parent $PSScriptRoot) ".env") } "Run scripts\setup-env.ps1"

if ($ok) { Write-Host "`nAll checks passed." -ForegroundColor Green } else { Write-Host "`nFix the failures above, then run scripts\start.ps1" -ForegroundColor Yellow }
