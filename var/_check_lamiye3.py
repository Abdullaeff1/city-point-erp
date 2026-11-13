"""Re-check Lamiyə Oct attendance in AxTrax vs ERP."""
from collections import Counter, defaultdict
from datetime import datetime

from django.db.models import Count, Min, Max
from django.utils import timezone

from apps.integrations.axtrax_mssql import connect
from apps.residents.models import AccessEvent, ResidentEmployee

emp = ResidentEmployee.objects.get(pk=692)
print("ERP", emp.pk, emp.full_name, emp.card_number)
print(
    "ERP oct",
    list(
        AccessEvent.objects.filter(
            employee_id=692,
            occurred_at__gte="2026-10-01",
            occurred_at__lt="2026-11-01",
        )
        .values("result", "event_type")
        .annotate(c=Count("id"))
    ),
)

conn = connect()
cur = conn.cursor(as_dict=True)

# 1) All event types for emp 1660 in October
cur.execute(
    """
SELECT e.iEventType, COUNT(*) AS c,
       MIN(e.dtEventReal) AS mn, MAX(e.dtEventReal) AS mx
FROM tblEvents e
WHERE e.IdEmpNum = 1660
  AND e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
GROUP BY e.iEventType
ORDER BY c DESC
"""
)
print("AX emp1660 oct by type", cur.fetchall())

# 2) Search by name / identification fragments
cur.execute(
    """
SELECT e.IdEmpNum, LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS full_name,
       e.iEventType, COUNT(*) AS c,
       MIN(e.dtEventReal) AS mn, MAX(e.dtEventReal) AS mx
FROM tblEvents e
WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND (
    e.tFullName LIKE '%Bayramova%Lami%'
    OR e.tFullName LIKE '%Lami%Bayramova%'
    OR e.tFullName LIKE '%003 957%'
    OR e.tFullName LIKE '%003957%'
  )
GROUP BY e.IdEmpNum, LTRIM(RTRIM(ISNULL(e.tFullName,''))), e.iEventType
ORDER BY c DESC
"""
)
print("AX name/card oct", cur.fetchall())

# 3) Employees matching Bayramova / 003957
cur.execute(
    """
SELECT iEmployeeNum, tFirstName, tMiddleName, tLastName, tIdentification,
       IdDepartment, IdAccessGroup
FROM tblEmployees
WHERE tIdentification LIKE '%3957%'
   OR tLastName LIKE '%Bayramova%'
   OR tFirstName LIKE '%Lami%'
"""
)
people = cur.fetchall()
print("AX people matches", len(people))
for p in people:
    if "bayram" in ((p.get("tLastName") or "") + (p.get("tFirstName") or "")).lower() or "3957" in (
        p.get("tIdentification") or ""
    ):
        print(" ", p)

# 4) Sample of type 17 anywhere with 003957 in name in oct
cur.execute(
    """
SELECT TOP 20 e.IdAutoEvents, e.IdEmpNum, e.dtEventReal, e.iEventType,
       LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS full_name,
       LTRIM(RTRIM(ISNULL(r.tDescReader,''))) AS reader,
       ISNULL(r.bReaderOut,0) AS reader_out
FROM tblEvents e
LEFT JOIN tblReader r ON r.IdReader = e.IdReader
WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND e.tFullName LIKE '%003 957%'
ORDER BY e.dtEventReal
"""
)
rows = cur.fetchall()
print("AX 003957 samples", len(rows))
for r in rows[:8]:
    print(" ", r)
print(" ... last")
for r in rows[-5:]:
    print(" ", r)

# 5) Event type dictionary if exists
for sql in [
    "SELECT TOP 50 * FROM tblEventType",
    "SELECT TOP 50 * FROM tblEventsType",
    "SELECT TOP 50 IdEventType, tDesc FROM tblEventTypes",
]:
    try:
        cur.execute(sql)
        print(sql, cur.fetchall()[:30])
        break
    except Exception as ex:
        print(sql, "ERR", getattr(ex, "args", ex))

# 6) Attendance tables?
for tbl in [
    "tblAttendance",
    "tblEmpAttendance",
    "tblWhoHasBeen",
    "tblWorkTime",
    "tblTimeAttend",
]:
    try:
        cur.execute(f"SELECT TOP 3 * FROM {tbl}")
        print(tbl, "OK", list(cur.fetchone().keys()) if cur.fetchone() else "empty")
    except Exception as ex:
        print(tbl, "no")

conn.close()
