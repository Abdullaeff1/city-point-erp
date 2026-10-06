"""Keep AxTrax event (+ optional people) sync running for the life of the app process."""

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
        while True:
            try:
                cursor = get_events_cursor()
                rows = fetch_granted_events(since_id=cursor, lookback_hours=lookback)
                if rows:
                    stats = sync_event_rows(rows, since_id=cursor, source="poll")
                    self.stdout.write(
                        f"synced rows={len(rows)} created={stats.get('created')} cursor={stats.get('cursor_after')}"
                    )
                else:
                    self.stdout.write(f"connected cursor={cursor} new=0")

                now = timezone.now().timestamp()
                if people_every > 0 and (now - last_people) >= people_every:
                    try:
                        pstats = sync_people_from_mssql()
                        last_people = now
                        self.stdout.write(
                            "people sync: "
                            f"updated={pstats.get('employees_updated', 0)} "
                            f"created={pstats.get('employees_created', 0)} "
                            f"deactivated={pstats.get('employees_deactivated', 0)} "
                            f"cards_reclaimed={pstats.get('cards_reclaimed', 0)}"
                        )
                    except Exception as people_exc:  # noqa: BLE001
                        self.stdout.write(self.style.ERROR(f"AxTrax people sync error: {people_exc}"))
            except Exception as exc:  # noqa: BLE001 — keep polling if SQL is briefly down
                self.stdout.write(self.style.ERROR(f"AxTrax poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(5, interval))
