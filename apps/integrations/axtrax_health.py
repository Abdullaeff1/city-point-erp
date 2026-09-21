"""AxTrax sync health helpers — ERP stays up when AxTrax is offline."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.integrations.axtrax_events_sync import EVENT_CURSOR_KEY, get_events_cursor
from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM
from apps.integrations.models import SyncLog, SyncStatus
from apps.residents.models import AccessEvent


def axtrax_sync_health(*, stale_after_minutes: int = 30) -> dict:
    """Return health snapshot for admin / ops dashboards."""
    now = timezone.now()
    last_event_sync = (
        SyncLog.objects.filter(system=AXTRAX_SYSTEM, operation="sync_events", status=SyncStatus.SUCCESS)
        .order_by("-created_at")
        .first()
    )
    last_people_sync = (
        SyncLog.objects.filter(system=AXTRAX_SYSTEM, operation="sync_people", status=SyncStatus.SUCCESS)
        .order_by("-created_at")
        .first()
    )
    last_fail = (
        SyncLog.objects.filter(system=AXTRAX_SYSTEM, status=SyncStatus.ERROR).order_by("-created_at").first()
    )
    last_access = AccessEvent.objects.order_by("-occurred_at").first()
    cursor = get_events_cursor()
    event_age = None
    events_stale = True
    if last_event_sync:
        event_age = now - last_event_sync.created_at
        events_stale = event_age > timedelta(minutes=stale_after_minutes)
    return {
        "cursor": cursor,
        "events_ok": bool(last_event_sync) and not events_stale,
        "events_stale": events_stale,
        "last_event_sync_at": last_event_sync.created_at if last_event_sync else None,
        "last_people_sync_at": last_people_sync.created_at if last_people_sync else None,
        "last_access_event_at": last_access.occurred_at if last_access else None,
        "last_error_at": last_fail.created_at if last_fail else None,
        "last_error_payload": (last_fail.response_payload if last_fail else None),
        "stale_after_minutes": stale_after_minutes,
        "cursor_operation": EVENT_CURSOR_KEY,
    }
