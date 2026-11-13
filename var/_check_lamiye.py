from apps.integrations.axtrax_mssql import connect

conn = connect()
cur = conn.cursor(as_dict=True)
cur.execute("SELECT TOP 1 * FROM tblEmployees WHERE iEmployeeNum=1660")
row = cur.fetchone()
if row:
    for k, v in row.items():
        kl = k.lower()
        if any(x in kl for x in ["card", "access", "ident", "name", "enable", "status", "emp", "dept"]):
            print(k, "=", repr(v))

cur.execute(
    "SELECT iEmployeeNum, tFirstName, tLastName, tIdentification, IdAccessGroup, iCardStatus "
    "FROM tblEmployees WHERE iEmployeeNum=1660"
)
print("lamiye", cur.fetchall())

cur.execute(
    "SELECT iEmployeeNum, tFirstName, tLastName, tIdentification, IdAccessGroup, iCardStatus "
    "FROM tblEmployees WHERE tIdentification LIKE %s OR tIdentification LIKE %s",
    ("%3958%", "%003 958%"),
)
print("colleague3958", cur.fetchall())

cur.execute(
    "SELECT COUNT(*) AS c FROM tblEvents WHERE IdEmpNum=1660 AND iEventType=18 "
    "AND dtEventReal >= %s",
    ("2026-10-30",),
)
print("denied_since_oct30", cur.fetchall())

cur.execute(
    "SELECT COUNT(*) AS c FROM tblEvents WHERE IdEmpNum=1660 AND iEventType=17"
)
print("total_granted_ever", cur.fetchall())
conn.close()
