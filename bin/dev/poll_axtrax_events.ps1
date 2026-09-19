# AxTraxNG → ERP AccessEvent poller (qısa interval).
# İstifadə: powershell -File bin/dev/poll_axtrax_events.ps1
# Default interval: 15 saniyə (mümkün qədər qısa; yük artarsa 30 edin)

param(
    [int]$IntervalSec = 15,
    [string]$HostSql = "172.31.104.10",
    [int]$Port = 1433,
    [string]$Database = "AxTrax1",
    [string]$User = "ReadOnlyerp",
    [string]$Password = $env:TURNSTILE_MSSQL_PASSWORD,
    [int]$LookbackHours = 48,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$OutFile = Join-Path $Root "var\axtrax_events.json"
$DevDir = Join-Path $Root "bin\dev"

if (-not $Password) {
    Write-Error "TURNSTILE_MSSQL_PASSWORD env lazımdır (və ya -Password verin). Şifrəni skriptə yazmayın."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "var") | Out-Null

function Get-Cursor {
    Push-Location $DevDir
    try {
        $out = docker compose exec -T web python manage.py sync_axtrax_events --show-cursor 2>$null
        if ($out -match "events_cursor=(\d+)") { return [int64]$Matches[1] }
        return [int64]0
    } finally {
        Pop-Location
    }
}

function Export-Events([int64]$sinceId) {
    $cs = "Server=$HostSql,$Port;Database=$Database;User ID=$User;Password=$Password;Encrypt=False;TrustServerCertificate=True;Connection Timeout=15"
    $conn = New-Object System.Data.SqlClient.SqlConnection $cs
    $conn.Open()
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandTimeout = 60
        $cmd.CommandText = @"
SELECT TOP 5000
  e.IdAutoEvents AS event_id,
  e.IdEmpNum AS employee_id,
  e.dtEventReal AS occurred_at,
  ISNULL(r.bReaderOut, 0) AS reader_out,
  e.IdReader AS reader_id,
  LTRIM(RTRIM(ISNULL(r.tDescReader, ''))) AS reader_name,
  e.iEventType AS event_type
FROM tblEvents e
LEFT JOIN tblReader r ON r.IdReader = e.IdReader
WHERE e.iEventType = 17
  AND e.IdEmpNum IS NOT NULL AND e.IdEmpNum <> 0
  AND e.IdAutoEvents > @since
  AND e.dtEventReal >= DATEADD(hour, -@hours, GETDATE())
  AND e.dtEventReal < '2100-01-01'
ORDER BY e.IdAutoEvents
"@
        $null = $cmd.Parameters.AddWithValue("@since", $sinceId)
        $null = $cmd.Parameters.AddWithValue("@hours", $LookbackHours)
        $r = $cmd.ExecuteReader()
        $rows = New-Object System.Collections.Generic.List[object]
        while ($r.Read()) {
            $dt = $r["occurred_at"]
            $occurred = if ($dt -is [datetime]) { $dt.ToString("o") } else { [string]$dt }
            $rows.Add([ordered]@{
                event_id = [int64]$r["event_id"]
                employee_id = [int]$r["employee_id"]
                occurred_at = $occurred
                reader_out = [bool]$r["reader_out"]
                reader_id = if ($r["reader_id"] -is [DBNull]) { $null } else { [int]$r["reader_id"] }
                reader_name = [string]$r["reader_name"]
                event_type = [int]$r["event_type"]
            })
        }
        $r.Close()
        $payload = [ordered]@{
            source = "AxTraxNG"
            exported_at = (Get-Date).ToString("o")
            since_id = $sinceId
            row_count = $rows.Count
            rows = $rows
        }
        $json = $payload | ConvertTo-Json -Depth 6 -Compress
        [System.IO.File]::WriteAllText($OutFile, $json, [System.Text.UTF8Encoding]::new($false))
        return $rows.Count
    } finally {
        $conn.Close()
    }
}

function Invoke-Sync {
    Push-Location $DevDir
    try {
        docker compose exec -T web python manage.py sync_axtrax_events --file=var/axtrax_events.json
    } finally {
        Pop-Location
    }
}

Write-Host "AxTrax events poller interval=${IntervalSec}s lookback=${LookbackHours}h"
while ($true) {
    $cursor = Get-Cursor
    $n = Export-Events -sinceId $cursor
    Write-Host "$(Get-Date -Format 'HH:mm:ss') exported=$n since=$cursor"
    if ($n -gt 0) {
        Invoke-Sync
    }
    if ($Once) { break }
    Start-Sleep -Seconds $IntervalSec
}
