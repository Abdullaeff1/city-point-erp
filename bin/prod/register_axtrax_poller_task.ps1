# Register AxTrax events poller as a Windows Scheduled Task (runs at logon / on failure restart).
# Run once in an elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File bin/prod/register_axtrax_poller_task.ps1
#
# Requires TURNSTILE_MSSQL_PASSWORD in Machine or User environment variables
# (Task Scheduler does not inherit interactive session env unless set permanently).

param(
    [string]$TaskName = "CityPoint-AxTrax-Events-Poller",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$IntervalSec = 15
)

$ErrorActionPreference = "Stop"
$poller = Join-Path $RepoRoot "bin\dev\poll_axtrax_events.ps1"
if (-not (Test-Path $poller)) {
    Write-Error "Poller not found: $poller"
}

$wrapper = Join-Path $RepoRoot "bin\prod\_run_axtrax_poller.cmd"
$cmdBody = @"
@echo off
cd /d "$RepoRoot"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$poller" -IntervalSec $IntervalSec
"@
[System.IO.File]::WriteAllText($wrapper, $cmdBody)

# Remove existing task if present
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    schtasks /Delete /TN $TaskName /F | Out-Null
}

# At startup, run as current user, highest available privileges
$tr = "`"$wrapper`""
schtasks /Create /TN $TaskName /TR $tr /SC ONSTART /RL HIGHEST /F
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks create failed (run elevated?)"
}

Write-Host "Scheduled task '$TaskName' registered."
Write-Host "Ensure TURNSTILE_MSSQL_PASSWORD is set as a User or Machine environment variable, then reboot or:"
Write-Host "  schtasks /Run /TN $TaskName"
Write-Host "Health: docker compose exec web python manage.py axtrax_sync_status"
