#!/usr/bin/env python
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg


def start_axtrax_poller():
    """Background poller in this container. Survives the later exec of runserver."""
    if os.environ.get("AXTRAX_POLL_ON_START", "1") != "1":
        print("AxTrax poller disabled (AXTRAX_POLL_ON_START!=1)")
        return
    if not os.environ.get("TURNSTILE_MSSQL_PASSWORD"):
        print("AxTrax poller skipped: TURNSTILE_MSSQL_PASSWORD is not set")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / "axtrax_poller.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "manage.py", "poll_axtrax"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print("AxTrax poller started (var/axtrax_poller.log)")


def wait_for_postgres():
    host = os.environ.get("POSTGRES_HOST", "db")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "citypoint")
    password = os.environ.get("POSTGRES_PASSWORD", "citypoint")
    dbname = os.environ.get("POSTGRES_DB", "citypoint")
    for attempt in range(60):
        try:
            with psycopg.connect(host=host, port=port, user=user, password=password, dbname=dbname):
                print("PostgreSQL is ready")
                return
        except Exception as exc:
            print(f"PostgreSQL not ready ({attempt + 1}/60): {exc}")
            time.sleep(2)
    raise SystemExit("PostgreSQL did not become ready")


def main():
    wait_for_postgres()
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    # Prefer Django compilemessages; fall back to pure-Python MO builder if msgfmt is missing.
    if subprocess.call([sys.executable, "manage.py", "compilemessages"]) != 0:
        subprocess.check_call([sys.executable, "scripts/compile_messages.py"])
    subprocess.call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    if os.environ.get("SEED_DEMO", "1") == "1":
        subprocess.check_call([sys.executable, "manage.py", "seed_demo"])
    start_axtrax_poller()
    os.execvp(sys.executable, [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"])


if __name__ == "__main__":
    main()
