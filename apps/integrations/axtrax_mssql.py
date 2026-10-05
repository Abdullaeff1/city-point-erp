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
