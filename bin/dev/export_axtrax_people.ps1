# AxTraxNG → var/axtrax_people.json (people + access groups / turn_back).
# İstifadə: powershell -File bin/dev/export_axtrax_people.ps1
# TURNSTILE_MSSQL_PASSWORD env lazımdır.

param(
    [string]$HostSql = "172.31.104.10",
    [int]$Port = 1433,
    [string]$Database = "AxTrax1",
    [string]$User = "ReadOnlyerp",
    [string]$Password = $env:TURNSTILE_MSSQL_PASSWORD
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$OutFile = Join-Path $Root "var\axtrax_people.json"

if (-not $Password) {
    Write-Error "TURNSTILE_MSSQL_PASSWORD env lazımdır (və ya -Password verin). Şifrəni skriptə yazmayın."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "var") | Out-Null

$cs = "Server=$HostSql,$Port;Database=$Database;User ID=$User;Password=$Password;Encrypt=False;TrustServerCertificate=True;Connection Timeout=30"
$conn = New-Object System.Data.SqlClient.SqlConnection $cs
$conn.Open()
try {
    $cmd = $conn.CreateCommand()
    $cmd.CommandTimeout = 180

    $cmd.CommandText = @"
SELECT
  g.IdAccessGroup AS id,
  LTRIM(RTRIM(g.tDescAccessGroup)) AS name,
  CASE WHEN EXISTS (
    SELECT 1
    FROM tblAccessTimeReader atr
    INNER JOIN tblReader r ON r.IdReader = atr.IdReader
    WHERE atr.IdAccessGroup = g.IdAccessGroup
      AND (r.tDescReader LIKE '%Back%' OR r.tDescReader LIKE '%back%')
  ) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS has_turn_back
FROM tblAccessGroup g
ORDER BY g.IdAccessGroup
"@
    $r = $cmd.ExecuteReader()
    $groups = New-Object System.Collections.Generic.List[object]
    while ($r.Read()) {
        $groups.Add([ordered]@{
            id = [int]$r["id"]
            name = [string]$r["name"]
            has_turn_back = [bool]$r["has_turn_back"]
        })
    }
    $r.Close()

    $cmd.CommandText = @"
SELECT
  d.IdDepartment AS department_id,
  LTRIM(RTRIM(d.tDescDepartment)) AS department_name,
  e.iEmployeeNum AS employee_id,
  LTRIM(RTRIM(e.tFirstName)) AS first_name,
  LTRIM(RTRIM(ISNULL(e.tMiddleName,''))) AS middle_name,
  LTRIM(RTRIM(e.tLastName)) AS last_name,
  LTRIM(RTRIM(ISNULL(e.tEmail,''))) AS email,
  LTRIM(RTRIM(ISNULL(e.tMobile,''))) AS mobile,
  LTRIM(RTRIM(ISNULL(e.tIdentification,''))) AS identification,
  e.IdAccessGroup AS access_group_id,
  LTRIM(RTRIM(ISNULL(ag.tDescAccessGroup,''))) AS access_group_name,
  CASE WHEN EXISTS (
    SELECT 1
    FROM tblAccessTimeReader atr
    INNER JOIN tblReader r ON r.IdReader = atr.IdReader
    WHERE atr.IdAccessGroup = e.IdAccessGroup
      AND (r.tDescReader LIKE '%Back%' OR r.tDescReader LIKE '%back%')
  ) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS has_turn_back,
  CASE WHEN e.bAccessDenied = 1 THEN CAST(0 AS bit) ELSE CAST(1 AS bit) END AS is_enabled,
  CAST(c.iCardCode AS nvarchar(32)) AS card_code,
  c.eCardStatus AS card_status
FROM tblEmployees e
INNER JOIN tblDepartment d ON d.IdDepartment = e.IdDepartment
LEFT JOIN tblAccessGroup ag ON ag.IdAccessGroup = e.IdAccessGroup
OUTER APPLY (
  SELECT TOP 1 c2.iCardCode, c2.eCardStatus
  FROM tblCard c2
  WHERE c2.IdEmpNum = e.iEmployeeNum AND c2.eCardStatus = 1
  ORDER BY c2.iCardCode
) c
WHERE e.iEmployeeNum IS NOT NULL
ORDER BY d.IdDepartment, e.iEmployeeNum
"@
    $r = $cmd.ExecuteReader()
    $rows = New-Object System.Collections.Generic.List[object]
    while ($r.Read()) {
        $rows.Add([ordered]@{
            department_id = [int]$r["department_id"]
            department_name = [string]$r["department_name"]
            employee_id = [int]$r["employee_id"]
            first_name = [string]$r["first_name"]
            middle_name = [string]$r["middle_name"]
            last_name = [string]$r["last_name"]
            email = [string]$r["email"]
            mobile = [string]$r["mobile"]
            identification = [string]$r["identification"]
            access_group_id = if ($r["access_group_id"] -is [DBNull]) { $null } else { [int]$r["access_group_id"] }
            access_group_name = [string]$r["access_group_name"]
            has_turn_back = [bool]$r["has_turn_back"]
            is_enabled = [bool]$r["is_enabled"]
            card_code = if ($r["card_code"] -is [DBNull]) { "" } else { [string]$r["card_code"] }
            card_status = if ($r["card_status"] -is [DBNull]) { $null } else { [int]$r["card_status"] }
        })
    }
    $r.Close()

    $payload = [ordered]@{
        source = "AxTraxNG"
        database = $Database
        exported_at = (Get-Date).ToString("o")
        row_count = $rows.Count
        access_groups = $groups
        rows = $rows
    }
    $json = $payload | ConvertTo-Json -Depth 6 -Compress
    [System.IO.File]::WriteAllText($OutFile, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Output "Wrote $($rows.Count) people + $($groups.Count) access groups → $OutFile"
}
finally {
    $conn.Close()
}
