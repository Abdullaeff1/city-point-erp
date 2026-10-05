#!/usr/bin/env python
import os
import subprocess
import sys
from pathlib import Path


def start_axtrax_poller():
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


def main():
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    start_axtrax_poller()
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "gunicorn",
            "config.wsgi:application",
            "--bind",
            "0.0.0.0:8000",
            "--workers",
            "3",
        ],
    )


if __name__ == "__main__":
    main()
