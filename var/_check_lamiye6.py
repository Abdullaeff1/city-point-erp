from apps.integrations.axtrax_mssql import connect

conn = connect()
cur = conn.cursor(as_dict=True)

# Card slot for Lamiyə vs Ülkər
for sql in [
    "SELECT TOP 5 * FROM tblCard WHERE iCardCode IN (16275, 23043)",
    "SELECT TOP 5 * FROM tblSlotCard WHERE IdCardSlot IN (1361, 1362) OR iCardCode IN (16275, 23043)",
    "SELECT TOP 5 * FROM ViewCardsByUser WHERE iEmployeeNum IN (1660, 1661)",
]:
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        print(sql[:50], "->", len(rows))
        for r in rows[:3]:
            print(" ", r)
    except Exception as ex:
        print("ERR", sql[:40], ex)

# the 5 only-18 employees in october
cur.execute(
    """
SELECT e.IdEmpNum,
       MAX(LTRIM(RTRIM(ISNULL(e.tFullName,'')))) AS n,
       COUNT(*) AS c18
FROM tblEvents e
WHERE e.dtEventReal >= '2026-10-01' AND e.dtEventReal < '2026-11-01'
  AND e.IdEmpNum IS NOT NULL AND e.IdEmpNum <> 0
GROUP BY e.IdEmpNum
HAVING SUM(CASE WHEN e.iEventType=17 THEN 1 ELSE 0 END)=0
   AND SUM(CASE WHEN e.iEventType=18 THEN 1 ELSE 0 END)>0
ORDER BY c18 DESC
"""
)
print("only18 people")
for r in cur.fetchall():
    print(r)

conn.close()
