from apps.integrations.axtrax_mssql import connect

conn = connect()
cur = conn.cursor(as_dict=True)

cur.execute("SELECT TOP 1 * FROM tblRptAttendance")
row = cur.fetchone()
print("tblRptAttendance cols", sorted(row.keys()) if row else None)

# Lamiyə in attendance report oct
for sql in [
    "SELECT TOP 30 * FROM tblRptAttendance WHERE iEmployeeNum=1660 AND dtDate >= '2026-10-01' AND dtDate < '2026-11-01' ORDER BY dtDate",
    "SELECT TOP 30 * FROM tblRptAttendance WHERE EmpNum=1660",
    "SELECT TOP 5 * FROM tblRptAttendance WHERE tFullName LIKE '%Bayramova%Lami%'",
]:
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        print(sql.split("WHERE")[0].strip(), "->", len(rows))
        for r in rows[:5]:
            print(" ", {k: r[k] for k in list(r)[:12]})
        if rows:
            break
    except Exception as ex:
        print("ERR", sql[:60], ex)

# tDesc on her events
cur.execute(
    """
SELECT TOP 10 e.iEventType, e.iEventSubType, e.tDesc, e.iCardCode, e.IdCardSlot, e.IdEmpSlot,
       LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS n
FROM tblEvents e WHERE e.IdEmpNum=1660
ORDER BY e.dtEventReal DESC
"""
)
print("tDesc samples")
for r in cur.fetchall():
    print(r)

# working colleague tDesc
cur.execute(
    """
SELECT TOP 5 e.iEventType, e.iEventSubType, e.tDesc, e.iCardCode, e.IdCardSlot,
       LTRIM(RTRIM(ISNULL(e.tFullName,''))) AS n
FROM tblEvents e WHERE e.IdEmpNum=1661 AND e.iEventType=17
ORDER BY e.dtEventReal DESC
"""
)
print("ulkər granted samples")
for r in cur.fetchall():
    print(r)

# Card tables
cur.execute(
    """
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME LIKE '%Card%'
ORDER BY TABLE_NAME
"""
)
print("card tables", [r["TABLE_NAME"] for r in cur.fetchall()])

# ViewTAEvents for 1660
try:
    cur.execute("SELECT TOP 1 * FROM ViewTAEvents")
    print("ViewTAEvents cols", sorted(cur.fetchone().keys()))
    cur.execute(
        "SELECT TOP 10 * FROM ViewTAEvents WHERE IdEmpNum=1660 OR iEmployeeNum=1660"
    )
except Exception as ex:
    print("ViewTAEvents", ex)
    try:
        cur.execute(
            """
            SELECT TOP 10 * FROM ViewTAEvents
            WHERE dtEventReal >= '2026-10-14' AND tFullName LIKE '%003 957%'
            """
        )
        print("view by name", cur.fetchall())
    except Exception as ex2:
        print("view2", ex2)

# How many employees have ONLY type 18 in october (no 17)?
cur.execute(
    """
SELECT COUNT(*) AS only18_emps FROM (
  SELECT e.IdEmpNum
  FROM tblEvents e
  WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
    AND e.IdEmpNum IS NOT NULL AND e.IdEmpNum <> 0
  GROUP BY e.IdEmpNum
  HAVING SUM(CASE WHEN e.iEventType=17 THEN 1 ELSE 0 END)=0
     AND SUM(CASE WHEN e.iEventType=18 THEN 1 ELSE 0 END)>0
) x
"""
)
print("emps with only type18 in oct", cur.fetchall())

conn.close()
