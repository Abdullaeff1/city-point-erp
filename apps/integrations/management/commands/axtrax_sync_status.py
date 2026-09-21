from django.core.management.base import BaseCommand

from apps.integrations.axtrax_health import axtrax_sync_health


class Command(BaseCommand):
    help = "Show AxTrax people/events sync health (does not call AxTrax)."

    def handle(self, *args, **options):
        h = axtrax_sync_health()
        self.stdout.write(f"events_ok={h['events_ok']} stale={h['events_stale']}")
        self.stdout.write(f"cursor={h['cursor']}")
        self.stdout.write(f"last_event_sync_at={h['last_event_sync_at']}")
        self.stdout.write(f"last_people_sync_at={h['last_people_sync_at']}")
        self.stdout.write(f"last_access_event_at={h['last_access_event_at']}")
        self.stdout.write(f"last_error_at={h['last_error_at']}")
