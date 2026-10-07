"""Keep AxTrax event (+ people) sync running for the life of the app process."""

import os
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.axtrax_events_sync import get_events_cursor, sync_event_rows
from apps.integrations.axtrax_mssql import fetch_granted_events
from apps.integrations.axtrax_people_sync import sync_people_from_mssql


class Command(BaseCommand):
    help = "Poll AxTraxNG and import new access events until stopped."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument(
            "--skip-people-bootstrap",
            action="store_true",
            help="Do not run an immediate people sync on startup",
        )

    def _sync_people(self) -> bool:
        try:
            pstats = sync_people_from_mssql()
            self.stdout.write(
                "people sync: "
                f"updated={pstats.get('employees_updated', 0)} "
                f"created={pstats.get('employees_created', 0)} "
                f"deactivated={pstats.get('employees_deactivated', 0)} "
                f"cards_reclaimed={pstats.get('cards_reclaimed', 0)}"
            )
            self.stdout.flush()
            return True
        except Exception as people_exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"AxTrax people sync error: {people_exc}"))
            self.stdout.flush()
            return False

    def _sync_events(self, *, lookback: int) -> None:
        cursor = get_events_cursor()
        rows = fetch_granted_events(since_id=cursor, lookback_hours=lookback)
        if rows:
            stats = sync_event_rows(rows, since_id=cursor, source="poll")
            self.stdout.write(
                f"synced rows={len(rows)} created={stats.get('created')} cursor={stats.get('cursor_after')}"
            )
        else:
            self.stdout.write(f"connected cursor={cursor} new=0")
        self.stdout.flush()

    def handle(self, *args, **options):
        interval = options["interval"] or int(os.environ.get("AXTRAX_POLL_INTERVAL", "15"))
        lookback = int(os.environ.get("AXTRAX_POLL_LOOKBACK_HOURS", "48"))
        people_every = int(os.environ.get("AXTRAX_PEOPLE_SYNC_INTERVAL", "300"))
        last_people = 0.0

        self.stdout.write(
            f"AxTrax poller started interval={interval}s lookback={lookback}h "
            f"people_every={people_every}s"
        )
        self.stdout.flush()

        # Always attempt connection immediately on process start.
        if not options["skip_people_bootstrap"] and people_every > 0:
            self.stdout.write("AxTrax bootstrap: people/companies/cards sync…")
            self.stdout.flush()
            if self._sync_people():
                last_people = timezone.now().timestamp()

        try:
            self._sync_events(lookback=lookback)
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"AxTrax poll error: {exc}"))
            self.stdout.flush()

        if options["once"]:
            return

        while True:
            time.sleep(max(5, interval))

            try:
                self._sync_events(lookback=lookback)
            except Exception as exc:  # noqa: BLE001 — keep polling if SQL is briefly down
                self.stdout.write(self.style.ERROR(f"AxTrax poll error: {exc}"))
                self.stdout.flush()

            if people_every <= 0:
                continue
            now = timezone.now().timestamp()
            # Retry sooner after failure, but never every event cycle (avoids log spam).
            due_in = people_every if last_people > 0 else min(60, people_every)
            if (now - last_people) >= due_in:
                last_people = now
                self._sync_people()
