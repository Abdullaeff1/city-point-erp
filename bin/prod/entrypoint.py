#!/usr/bin/env python
import os
import subprocess
import sys


def main():
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "collectstatic", "--noinput"])
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
