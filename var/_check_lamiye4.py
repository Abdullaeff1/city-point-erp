"""Compare Lamiyə (denied-only) vs working L.B.Audit colleague event types."""
from apps.integrations.axtrax_mssql import connect

conn = connect()
cur = conn.cursor(as_dict=True)

# Ülkər 003958 from earlier nov punches
cur.execute(
    """
SELECT iEmployeeNum, tFirstName, tMiddleName, tLastName, tIdentification, IdAccessGroup, IdDepartment
FROM tblEmployees
WHERE tIdentification LIKE '%3958%' OR tIdentification LIKE '%003958%'
   OR (tFirstName LIKE '%lk_r%' AND tLastName LIKE '%mm_dova%')
"""
)
print("ulkər candidates", cur.fetchall())

# working employee with many type 17 in oct at same readers
cur.execute(
    """
SELECT TOP 5 e.IdEmpNum, LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS n,
       SUM(CASE WHEN e.iEventType=17 THEN 1 ELSE 0 END) AS g17,
       SUM(CASE WHEN e.iEventType=18 THEN 1 ELSE 0 END) AS d18,
       SUM(CASE WHEN e.iEventType=33 THEN 1 ELSE 0 END) AS d33
FROM tblEvents e
WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND e.tFullName LIKE '%L.B%' OR 1=0
GROUP BY e.IdEmpNum, LTRIM(RTRIM(ISNULL(e.tFullName,'')))
"""
)

# Find emp with identification 003958
cur.execute(
    """
SELECT iEmployeeNum, tFirstName, tLastName, tIdentification, IdAccessGroup
FROM tblEmployees WHERE REPLACE(tIdentification,' ','') = '003958'
"""
)
print("exact 003958", cur.fetchall())

cur.execute(
    """
SELECT e.IdEmpNum, MAX(LTRIM(RTRIM(ISNULL(e.tFullName,'')))) AS n,
       SUM(CASE WHEN e.iEventType=17 THEN 1 ELSE 0 END) AS g17,
       SUM(CASE WHEN e.iEventType=18 THEN 1 ELSE 0 END) AS d18
FROM tblEvents e
WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND e.tFullName LIKE '%003 958%'
GROUP BY e.IdEmpNum
"""
)
print("events 003958", cur.fetchall())

# Sample type 17 vs 18 descriptions - any text columns on tblEvents
cur.execute("SELECT TOP 1 * FROM tblEvents WHERE IdEmpNum=1660")
row = cur.fetchone()
print("tblEvents columns:", sorted(row.keys()))

# Compare same reader: granted for others + denied for lamiye same minute
cur.execute(
    """
SELECT TOP 10 e.dtEventReal, e.IdEmpNum, e.iEventType,
       LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS n,
       LTRIM(RTRIM(ISNULL(r.tDescReader,''))) AS reader
FROM tblEvents e
LEFT JOIN tblReader r ON r.IdReader=e.IdReader
WHERE e.dtEventReal >= '2026-10-14 09:00:00' AND e.dtEventReal < '2026-10-14 10:00:00'
  AND r.tDescReader LIKE '%F1Ent5IN%'
  AND e.iEventType IN (17,18)
ORDER BY e.dtEventReal
"""
)
print("same reader morning mix:")
for r in cur.fetchall():
    print(" ", r)

# Does AxTrax attendance use type 18 as IN/OUT? Daily first/last for 1660 from type 18
cur.execute(
    """
SELECT CAST(e.dtEventReal AS DATE) AS d,
       MIN(CASE WHEN ISNULL(r.bReaderOut,0)=0 THEN e.dtEventReal END) AS first_in,
       MAX(CASE WHEN ISNULL(r.bReaderOut,0)=1 THEN e.dtEventReal END) AS last_out,
       COUNT(*) AS c
FROM tblEvents e
LEFT JOIN tblReader r ON r.IdReader=e.IdReader
WHERE e.IdEmpNum=1660
  AND e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND e.iEventType=18
GROUP BY CAST(e.dtEventReal AS DATE)
ORDER BY d
"""
)
days = cur.fetchall()
print("AX type18 daily attendance-like rows", len(days))
for d in days:
    print(" ", d)

# Event type meanings from any lookup / info schema
cur.execute(
    """
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME LIKE '%Event%' OR TABLE_NAME LIKE '%Attend%' OR TABLE_NAME LIKE '%Who%'
ORDER BY TABLE_NAME
"""
)
print("tables", [r["TABLE_NAME"] for r in cur.fetchall()])

conn.close()
