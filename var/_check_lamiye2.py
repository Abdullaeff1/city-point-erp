from apps.integrations.axtrax_mssql import connect

conn = connect()
cur = conn.cursor(as_dict=True)
cur.execute(
    "SELECT iEventType, COUNT(*) AS c, MIN(dtEventReal) AS mn, MAX(dtEventReal) AS mx "
    "FROM tblEvents WHERE IdEmpNum=1660 GROUP BY iEventType"
)
print("all_time_by_type", cur.fetchall())

cur.execute(
    "SELECT TOP 5 dtEventReal, iEventType FROM tblEvents "
    "WHERE IdEmpNum=1660 ORDER BY dtEventReal DESC"
)
print("latest", cur.fetchall())

# access group 5 name
cur.execute(
    "SELECT IdAccessGroup, tDescAccessGroup FROM tblAccessGroup WHERE IdAccessGroup=5"
)
print("group", cur.fetchall())

# cards linked to emp 1660 if table exists
for sql in [
    "SELECT TOP 5 * FROM tblCards WHERE iEmployeeNum=1660",
    "SELECT TOP 5 * FROM tblEmpCards WHERE iEmployeeNum=1660",
    "SELECT TOP 5 * FROM tblEmployeeCards WHERE iEmployeeNum=1660",
]:
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        print(sql, "->", rows[:3] if rows else "empty")
        if rows:
            print("keys", list(rows[0].keys()))
    except Exception as ex:
        print(sql, "ERR", ex)
conn.close()
