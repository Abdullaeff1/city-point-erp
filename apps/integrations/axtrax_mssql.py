"""Read-only AxTraxNG SQL access used by the in-app poller."""

from __future__ import annotations

import os
from datetime import datetime


def mssql_settings() -> dict:
    password = os.environ.get("TURNSTILE_MSSQL_PASSWORD") or ""
    if not password:
        raise RuntimeError("TURNSTILE_MSSQL_PASSWORD is not set")
    return {
        "server": os.environ.get("TURNSTILE_MSSQL_HOST", "172.31.104.10"),
        "port": int(os.environ.get("TURNSTILE_MSSQL_PORT", "1433")),
        "user": os.environ.get("TURNSTILE_MSSQL_USER", "ReadOnlyerp"),
        "password": password,
        "database": os.environ.get("TURNSTILE_MSSQL_DATABASE", "AxTrax1"),
    }


def connect():
    import pymssql

    cfg = mssql_settings()
    return pymssql.connect(
        server=cfg["server"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        login_timeout=15,
        timeout=60,
        tds_version="7.4",
    )


def fetch_granted_events(*, since_id: int, lookback_hours: int = 48, limit: int = 5000) -> list[dict]:
    """Access-granted rows newer than the ERP cursor (same filter as the host poller)."""
    sql = """
SELECT TOP %d
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
  AND e.IdAutoEvents > %%s
  AND e.dtEventReal >= DATEADD(hour, -%%s, GETDATE())
  AND e.dtEventReal < '2100-01-01'
ORDER BY e.IdAutoEvents
""" % int(limit)
    conn = connect()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, (int(since_id), int(lookback_hours)))
        return _normalize_event_rows(cur.fetchall())
    finally:
        conn.close()


def fetch_granted_events_since(
    since_dt: datetime,
    *,
    after_id: int = 0,
    limit: int = 5000,
) -> list[dict]:
    """Historical catch-up: access-granted rows from ``since_dt`` with IdAutoEvents > after_id."""
    sql = """
SELECT TOP %d
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
  AND e.IdAutoEvents > %%s
  AND e.dtEventReal >= %%s
  AND e.dtEventReal < '2100-01-01'
ORDER BY e.IdAutoEvents
""" % int(limit)
    conn = connect()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, (int(after_id), since_dt))
        return _normalize_event_rows(cur.fetchall())
    finally:
        conn.close()


def _normalize_event_rows(raw_rows) -> list[dict]:
    rows = []
    for raw in raw_rows:
        occurred = raw.get("occurred_at")
        if isinstance(occurred, datetime):
            occurred = occurred.isoformat()
        reader_id = raw.get("reader_id")
        rows.append(
            {
                "event_id": int(raw["event_id"]),
                "employee_id": int(raw["employee_id"]),
                "occurred_at": occurred,
                "reader_out": bool(raw.get("reader_out")),
                "reader_id": None if reader_id is None else int(reader_id),
                "reader_name": str(raw.get("reader_name") or ""),
                "event_type": int(raw.get("event_type") or 0),
            }
        )
    return rows


PEOPLE_SQL = """
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
      AND (r.tDescReader LIKE '%%Back%%' OR r.tDescReader LIKE '%%back%%')
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
"""

ACCESS_GROUPS_SQL = """
SELECT
  g.IdAccessGroup AS id,
  LTRIM(RTRIM(g.tDescAccessGroup)) AS name,
  CASE WHEN EXISTS (
    SELECT 1
    FROM tblAccessTimeReader atr
    INNER JOIN tblReader r ON r.IdReader = atr.IdReader
    WHERE atr.IdAccessGroup = g.IdAccessGroup
      AND (r.tDescReader LIKE '%%Back%%' OR r.tDescReader LIKE '%%back%%')
  ) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS has_turn_back
FROM tblAccessGroup g
ORDER BY g.IdAccessGroup
"""


def fetch_people_payload() -> dict:
    """Live AxTrax people + access groups (same shape as var/axtrax_people.json)."""
    conn = connect()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(ACCESS_GROUPS_SQL)
        groups = []
        for raw in cur.fetchall() or []:
            groups.append(
                {
                    "id": int(raw["id"]),
                    "name": str(raw.get("name") or ""),
                    "has_turn_back": bool(raw.get("has_turn_back")),
                }
            )
        cur.execute(PEOPLE_SQL)
        rows = []
        for raw in cur.fetchall() or []:
            ag = raw.get("access_group_id")
            cs = raw.get("card_status")
            rows.append(
                {
                    "department_id": int(raw["department_id"]),
                    "department_name": str(raw.get("department_name") or ""),
                    "employee_id": int(raw["employee_id"]),
                    "first_name": str(raw.get("first_name") or ""),
                    "middle_name": str(raw.get("middle_name") or ""),
                    "last_name": str(raw.get("last_name") or ""),
                    "email": str(raw.get("email") or ""),
                    "mobile": str(raw.get("mobile") or ""),
                    "identification": str(raw.get("identification") or ""),
                    "access_group_id": None if ag is None else int(ag),
                    "access_group_name": str(raw.get("access_group_name") or ""),
                    "has_turn_back": bool(raw.get("has_turn_back")),
                    "is_enabled": bool(raw.get("is_enabled")),
                    "card_code": "" if raw.get("card_code") is None else str(raw.get("card_code")),
                    "card_status": None if cs is None else int(cs),
                }
            )
        return {
            "source": "AxTraxNG",
            "database": mssql_settings()["database"],
            "exported_at": datetime.now().isoformat(),
            "row_count": len(rows),
            "access_groups": groups,
            "rows": rows,
        }
    finally:
        conn.close()
