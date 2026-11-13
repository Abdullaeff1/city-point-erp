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


def start_zoho_announcements_poller():
    """Background poller: Zoho Mail all-residents → portal building announcements."""
    if os.environ.get("ZOHO_POLL_ON_START", "0") != "1":
        print("Zoho announcements poller disabled (ZOHO_POLL_ON_START!=1)")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "zoho_announcements_poller.log"
    log = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "poll_zoho_announcements"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"Zoho announcements poller started pid={proc.pid} log={log_path}")


def start_ticket_sla_escalation_poller():
    if os.environ.get("TICKET_SLA_POLL_ON_START", "0") != "1":
        print("Ticket SLA escalation poller disabled (TICKET_SLA_POLL_ON_START!=1)")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "ticket_sla_escalation_poller.log"
    log = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "poll_ticket_sla_escalations"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"Ticket SLA escalation poller started pid={proc.pid} log={log_path}")


def start_crm_reminder_poller():
    if os.environ.get("CRM_REMINDER_POLL_ON_START", "0") != "1":
        print("CRM reminder poller disabled (CRM_REMINDER_POLL_ON_START!=1)")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "crm_reminder_poller.log"
    log = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "poll_crm_reminders"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"CRM reminder poller started pid={proc.pid} log={log_path}")


def start_outlook_announcements_poller():
    """Legacy: Outlook shared mailbox → portal announcements (prefer Zoho)."""
    if os.environ.get("OUTLOOK_POLL_ON_START", "0") != "1":
        print("Outlook announcements poller disabled (OUTLOOK_POLL_ON_START!=1)")
        return
    log_dir = Path("var")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "outlook_announcements_poller.log"
    log = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "poll_outlook_announcements"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"Outlook announcements poller started pid={proc.pid} log={log_path}")


def main():
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    start_axtrax_poller()
    start_zoho_announcements_poller()
    start_outlook_announcements_poller()
    start_ticket_sla_escalation_poller()
    start_crm_reminder_poller()
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
