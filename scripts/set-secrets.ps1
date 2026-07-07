<#
.SYNOPSIS
  Interactively set the repo's GitHub Actions secrets one by one, with hidden
  input for sensitive values. Optionally writes a local .env for local runs.

.DESCRIPTION
  Prompts for each secret and pushes it with `gh secret set` over stdin (values
  never appear in your shell history or the process list). Nothing is committed.

.EXAMPLE
  .\scripts\set-secrets.ps1
  .\scripts\set-secrets.ps1 -WriteEnv
#>
[CmdletBinding()]
param(
    [string]$Repo = "dipakboyed/airline-fare-finder",
    [string]$GhUser = "dipakboyed",
    [switch]$WriteEnv
)

$ErrorActionPreference = "Stop"

function Read-Plain {
    param([string]$Prompt, [string]$Default = "")
    $v = Read-Host -Prompt $Prompt
    if ([string]::IsNullOrWhiteSpace($v) -and $Default) { return $Default }
    return $v
}

function Read-Secret {
    param([string]$Prompt)
    $s = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Set-GhSecret {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        Write-Host "  - $Name : skipped (empty)" -ForegroundColor DarkYellow
        return
    }
    $Value | gh secret set $Name --repo $Repo | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "  - $Name : set" -ForegroundColor Green }
    else { Write-Host "  - $Name : FAILED" -ForegroundColor Red }
}

Write-Host "Setting secrets on $Repo (gh account: $GhUser)`n" -ForegroundColor Cyan
gh auth switch --user $GhUser | Out-Null

# --- Amadeus (https://developers.amadeus.com -> My Self-Service Workspace) ---
Write-Host "[1/6] Amadeus API Key (Client ID)"
$amadeusId = Read-Plain "      AMADEUS_CLIENT_ID"

Write-Host "[2/6] Amadeus API Secret (hidden)"
$amadeusSecret = Read-Secret "      AMADEUS_CLIENT_SECRET"

Write-Host "[3/6] Amadeus environment: 'test' or 'production' [test]"
$amadeusEnv = Read-Plain "      AMADEUS_ENV" "test"

# --- Gmail (optional; myaccount.google.com -> Security -> App passwords) ---
Write-Host "`n[4/6] Gmail sender address (optional; Enter to skip email)"
$mailUser = Read-Plain "      MAIL_USERNAME"

Write-Host "[5/6] Gmail App Password (hidden; optional)"
$mailPass = Read-Secret "      MAIL_PASSWORD"

Write-Host "[6/6] Deliver reports to [diboyed@gmail.com]"
$mailTo = Read-Plain "      MAIL_TO" "diboyed@gmail.com"

Write-Host "`nPushing secrets..." -ForegroundColor Cyan
Set-GhSecret "AMADEUS_CLIENT_ID"     $amadeusId
Set-GhSecret "AMADEUS_CLIENT_SECRET" $amadeusSecret
Set-GhSecret "AMADEUS_ENV"           $amadeusEnv
Set-GhSecret "MAIL_USERNAME"         $mailUser
Set-GhSecret "MAIL_PASSWORD"         $mailPass
Set-GhSecret "MAIL_TO"               $mailTo

if ($WriteEnv) {
    $envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
    $lines = @(
        "AMADEUS_CLIENT_ID=$amadeusId",
        "AMADEUS_CLIENT_SECRET=$amadeusSecret",
        "AMADEUS_ENV=$amadeusEnv"
    )
    if ($mailUser) { $lines += "MAIL_USERNAME=$mailUser" }
    if ($mailPass) { $lines += "MAIL_PASSWORD=$mailPass" }
    if ($mailTo)   { $lines += "MAIL_TO=$mailTo" }
    Set-Content -Path $envPath -Value $lines -Encoding utf8
    Write-Host "`nWrote local $envPath (gitignored)." -ForegroundColor Green
}

Write-Host "`nDone. Current secrets:" -ForegroundColor Cyan
gh secret list --repo $Repo
Write-Host "`nTest locally:  python -m farefinder run --config config/searches/sea-ccu.yaml --dry-run"
Write-Host "Trigger cloud: gh workflow run fares-daily.yml --repo $Repo"
