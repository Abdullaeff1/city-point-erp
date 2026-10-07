#!/usr/bin/env python
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg


def start_axtrax_poller():
    """Background poller: connects to AxTrax on every container start."""
    if os.environ.get("AXTRAX_POLL_ON_START", "1") != "1":
        print("AxTrax poller disabled (AXTRAX_POLL_ON_START!=1)")
        return
    if not os.environ.get("TURNSTILE_MSSQL_PASSWORD"):
        print("AxTrax poller skipped: TURNSTILE_MSSQL_PASSWORD is not set")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "axtrax_poller.log"
    log = open(log_path, "a", encoding="utf-8")
    # Bootstrap once in foreground so first login already has fresh people/events attempt.
    if os.environ.get("AXTRAX_BOOTSTRAP_ON_START", "1") == "1":
        print("AxTrax bootstrap (one-shot)…")
        try:
            subprocess.call(
                [sys.executable, "manage.py", "poll_axtrax", "--once"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=int(os.environ.get("AXTRAX_BOOTSTRAP_TIMEOUT", "120")),
            )
        except subprocess.TimeoutExpired:
            print("AxTrax bootstrap timed out — continuing; background poller will retry")
        except Exception as exc:  # noqa: BLE001
            print(f"AxTrax bootstrap error: {exc}")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "poll_axtrax"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"AxTrax poller started pid={proc.pid} log={log_path}")


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
    if subprocess.call([sys.executable, "manage.py", "compilemessages"]) != 0:
        subprocess.check_call([sys.executable, "scripts/compile_messages.py"])
    subprocess.call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    if os.environ.get("SEED_DEMO", "1") == "1":
        subprocess.check_call([sys.executable, "manage.py", "seed_demo"])
    start_axtrax_poller()
    # OneDrive-mounted trees can crash Django autoreloader with Errno 5 (I/O error).
    cmd = [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"]
    if os.environ.get("RUNSERVER_NORELOAD", "1") == "1":
        cmd.append("--noreload")
    os.execvp(sys.executable, cmd)


if __name__ == "__main__":
    main()
