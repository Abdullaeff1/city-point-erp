"""Import AxTraxNG access-granted events into AccessEvent (poll-friendly)."""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM
from apps.integrations.models import ExternalIdentity, SyncLog, SyncStatus
from apps.residents.models import AccessEvent, AccessEventType, ResidentEmployee

EVENT_CURSOR_KEY = "events_cursor"
ACCESS_GRANTED_TYPE = 17


def load_export(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def get_events_cursor() -> int:
    log = (
        SyncLog.objects.filter(system=AXTRAX_SYSTEM, operation=EVENT_CURSOR_KEY, status=SyncStatus.SUCCESS)
        .order_by("-created_at")
        .first()
    )
    if not log or not isinstance(log.response_payload, dict):
        return 0
    try:
        return int(log.response_payload.get("last_id") or 0)
    except (TypeError, ValueError):
        return 0


def set_events_cursor(last_id: int, stats: dict | None = None) -> None:
    SyncLog.objects.create(
        system=AXTRAX_SYSTEM,
        operation=EVENT_CURSOR_KEY,
        status=SyncStatus.SUCCESS,
        response_payload={"last_id": int(last_id), **(stats or {})},
    )


def _employee_map() -> dict[int, int]:
    """AxTrax emp id → ResidentEmployee pk."""
    ct = ContentType.objects.get_for_model(ResidentEmployee)
    mapping = {}
    for ext_id, entity_id in ExternalIdentity.objects.filter(
        system=AXTRAX_SYSTEM,
        external_id__startswith="emp:",
        entity_type=ct,
    ).values_list("external_id", "entity_id"):
        try:
            mapping[int(str(ext_id).split(":", 1)[1])] = int(entity_id)
        except (IndexError, ValueError):
            continue
    return mapping


def _parse_occurred_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value).replace(" ", "T", 1)) if value else None
        if dt is None:
            try:
                dt = datetime.fromisoformat(str(value))
            except ValueError:
                return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    # Skip corrupt far-future AxTrax timestamps
    if dt.year >= 2100:
        return None
    return dt


def _event_type(reader_out) -> str:
    if reader_out in (True, 1, "1", "true", "True"):
        return AccessEventType.OUT
    return AccessEventType.IN


@transaction.atomic
def sync_events_from_export(path: Path, *, since_id: int | None = None) -> dict:
    payload = load_export(path)
    rows = payload.get("rows") or []
    cursor = get_events_cursor() if since_id is None else int(since_id)
    emp_map = _employee_map()
    event_ct = ContentType.objects.get_for_model(AccessEvent)

    stats = {
        "rows_in_file": len(rows),
        "cursor_before": cursor,
        "created": 0,
        "skipped_existing": 0,
        "skipped_unmapped": 0,
        "skipped_bad_time": 0,
        "skipped_old": 0,
    }
    max_id = cursor

    for row in rows:
        try:
            event_id = int(row["event_id"])
            emp_num = int(row.get("employee_id") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if event_id <= cursor:
            stats["skipped_old"] += 1
            continue
        max_id = max(max_id, event_id)

        ext_key = f"event:{event_id}"
        if ExternalIdentity.objects.filter(system=AXTRAX_SYSTEM, external_id=ext_key).exists():
            stats["skipped_existing"] += 1
            continue

        employee_pk = emp_map.get(emp_num)
        if not employee_pk:
            stats["skipped_unmapped"] += 1
            continue

        occurred_at = _parse_occurred_at(row.get("occurred_at"))
        if not occurred_at:
            stats["skipped_bad_time"] += 1
            continue

        employee = ResidentEmployee.objects.filter(pk=employee_pk).only(
            "id", "full_name", "card_number"
        ).first()
        if not employee:
            stats["skipped_unmapped"] += 1
            continue

        event = AccessEvent.objects.create(
            employee_id=employee.pk,
            event_type=_event_type(row.get("reader_out")),
            occurred_at=occurred_at,
            employee_name=employee.full_name[:160],
            card_number=(employee.card_number or "")[:32],
            axtrax_employee_id=emp_num,
        )
        ExternalIdentity.objects.create(
            system=AXTRAX_SYSTEM,
            external_id=ext_key,
            entity_type=event_ct,
            entity_id=event.pk,
            last_sync_at=timezone.now(),
            last_status=SyncStatus.SUCCESS,
        )
        stats["created"] += 1

    if max_id > cursor:
        set_events_cursor(max_id, stats={"created": stats["created"]})
    stats["cursor_after"] = max_id if max_id > cursor else cursor

    SyncLog.objects.create(
        system=AXTRAX_SYSTEM,
        operation="sync_events",
        status=SyncStatus.SUCCESS,
        request_payload={"path": str(path), "since_id": cursor},
        response_payload=stats,
    )
    return stats
