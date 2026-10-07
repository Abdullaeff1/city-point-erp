#!/usr/bin/env python
import os
import subprocess
import sys
from pathlib import Path


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
    if os.environ.get("AXTRAX_BOOTSTRAP_ON_START", "1") == "1":
        print("AxTrax bootstrap (one-shot)…")
        try:
            subprocess.call(
                [sys.executable, "manage.py", "poll_axtrax", "--once"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=int(os.environ.get("AXTRAX_BOOTSTRAP_TIMEOUT", "180")),
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
