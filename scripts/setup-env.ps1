<#
.SYNOPSIS
  Creates .env from .env.example with freshly generated secrets. Safe to re-run:
  an existing .env is never overwritten.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$example = Join-Path $root ".env.example"

function New-Secret([int]$bytes = 48) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    # URL-safe base64 without padding
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (Test-Path $envFile) {
    # Existing install: only add settings introduced by later releases; never change values.
    $existing = [System.IO.File]::ReadAllText($envFile)
    if ($existing -notmatch '(?m)^SECRETS_MASTER_KEY=\S' -or $existing -match '(?m)^SECRETS_MASTER_KEY=CHANGE_ME') {
        $existing = $existing -replace '(?m)^SECRETS_MASTER_KEY=.*(\r?\n)?', ''
        $existing = $existing.TrimEnd() + "`n`n# Added by setup-env: encrypts stored AI provider API keys.`nSECRETS_MASTER_KEY=$(New-Secret 32)`n"
        [System.IO.File]::WriteAllText($envFile, ($existing -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding $false))
        Write-Host "Added SECRETS_MASTER_KEY to existing .env." -ForegroundColor Green
    } else {
        Write-Host ".env already exists - leaving it unchanged." -ForegroundColor Yellow
    }
    exit 0
}

$content = Get-Content $example -Raw
$content = $content -replace '(?m)^POSTGRES_PASSWORD=.*$', "POSTGRES_PASSWORD=$(New-Secret 24)"
$content = $content -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$(New-Secret 48)"
$content = $content -replace '(?m)^SECRETS_MASTER_KEY=.*$', "SECRETS_MASTER_KEY=$(New-Secret 32)"
# Write LF line endings without BOM so Docker Compose parses the file cleanly.
[System.IO.File]::WriteAllText($envFile, ($content -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding $false))
Write-Host "Created .env with new random secrets." -ForegroundColor Green
