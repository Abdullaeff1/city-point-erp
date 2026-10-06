#!/usr/bin/env python3
"""Inspect AxTrax employee/card assignment for known badge issues."""
from __future__ import annotations

import os

import pymssql


def main():
    conn = pymssql.connect(
        server=os.environ["TURNSTILE_MSSQL_HOST"],
        port=int(os.environ.get("TURNSTILE_MSSQL_PORT", "1433")),
        user=os.environ["TURNSTILE_MSSQL_USER"],
        password=os.environ["TURNSTILE_MSSQL_PASSWORD"],
        database=os.environ["TURNSTILE_MSSQL_DATABASE"],
    )
    cur = conn.cursor(as_dict=True)

    print("==== tblCard columns")
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME='tblCard' ORDER BY ORDINAL_POSITION"
    )
    for r in cur.fetchall():
        print(r)

    print("\n==== employees by identification / name")
    cur.execute(
        """
        SELECT e.iEmployeeNum, e.tFirstName, e.tMiddleName, e.tLastName,
               e.tIdentification, e.bAccessDenied, d.tDescDepartment
        FROM tblEmployees e
        INNER JOIN tblDepartment d ON d.IdDepartment = e.IdDepartment
        WHERE e.tIdentification LIKE '%6001%'
           OR e.tIdentification LIKE '%6536%'
           OR e.tFirstName LIKE N'%Namik%'
           OR e.tLastName LIKE N'%Cumay%'
           OR e.tLastName LIKE N'%Mahammad%'
           OR e.tLastName LIKE N'%Məhəmməd%'
           OR e.tLastName LIKE N'%Mehemmed%'
        """
    )
    emps = cur.fetchall()
    for r in emps:
        print(r)

    print("\n==== cards for those employees / badge codes")
    cur.execute(
        """
        SELECT c.*, e.tFirstName, e.tLastName, e.tIdentification, d.tDescDepartment
        FROM tblCard c
        LEFT JOIN tblEmployees e ON e.iEmployeeNum = c.IdEmpNum
        LEFT JOIN tblDepartment d ON d.IdDepartment = e.IdDepartment
        WHERE CAST(c.iCardCode AS nvarchar(32)) IN ('6001','6536','006001','006536')
           OR c.IdEmpNum IN (
             SELECT iEmployeeNum FROM tblEmployees
             WHERE tIdentification LIKE '%6001%' OR tIdentification LIKE '%6536%'
                OR tFirstName LIKE N'%Namik%' OR tLastName LIKE N'%Cumay%'
           )
        """
    )
    try:
        for r in cur.fetchall():
            print({k: r[k] for k in r})
    except Exception as exc:
        print("card query err", exc)
        # simpler
        cur.execute(
            """
            SELECT c.iCardCode, c.IdEmpNum, c.eCardStatus, e.tFirstName, e.tLastName,
                   e.tIdentification, d.tDescDepartment
            FROM tblCard c
            LEFT JOIN tblEmployees e ON e.iEmployeeNum = c.IdEmpNum
            LEFT JOIN tblDepartment d ON d.IdDepartment = e.IdDepartment
            WHERE e.tFirstName LIKE N'%Namik%' OR e.tLastName LIKE N'%Cumay%'
               OR e.tIdentification LIKE '%6001%' OR e.tIdentification LIKE '%6536%'
            """
        )
        for r in cur.fetchall():
            print(r)

    # Recent events for these cards / employees
    print("\n==== recent events involving badge-like codes or those emp ids")
    emp_ids = [r["iEmployeeNum"] for r in emps]
    if emp_ids:
        ids = ",".join(str(i) for i in emp_ids)
        cur.execute(
            f"""
            SELECT TOP 20 IdAutoEvents, IdEmpNum, iEventType, dtEventReal, IdReader
            FROM tblEvents
            WHERE IdEmpNum IN ({ids})
            ORDER BY IdAutoEvents DESC
            """
        )
        for r in cur.fetchall():
            print(r)

    conn.close()


if __name__ == "__main__":
    main()
