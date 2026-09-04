#!/usr/bin/env python
import os
import subprocess
import sys
import time

import psycopg


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
    subprocess.check_call([sys.executable, "manage.py", "makemigrations", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    subprocess.call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    if os.environ.get("SEED_DEMO", "1") == "1":
        subprocess.check_call([sys.executable, "manage.py", "seed_demo"])
    os.execvp(sys.executable, [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"])


if __name__ == "__main__":
    main()
