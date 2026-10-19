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
from apps.residents.models import AccessEvent, AccessEventType, AccessResult, ResidentEmployee

EVENT_CURSOR_KEY = "events_cursor"
ACCESS_GRANTED_TYPE = 17
ACCESS_DENIED_TYPES = {18, 33}


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


def _access_result(ax_type) -> str:
    try:
        code = int(ax_type or ACCESS_GRANTED_TYPE)
    except (TypeError, ValueError):
        code = ACCESS_GRANTED_TYPE
    if code in ACCESS_DENIED_TYPES:
        return AccessResult.DENIED
    return AccessResult.GRANTED


def _snapshot_name(row, employee) -> str:
    if employee is not None:
        return (employee.full_name or "")[:160]
    raw = " ".join(str(row.get("full_name") or "").split())
    if raw.lower().startswith("card"):
        code = str(row.get("card_code") or "").strip()
        return (f"Kart {code}" if code else "Naməlum kart")[:160]
    head = raw.split("(Card", 1)[0].strip(" ,")
    return (head or raw or "Naməlum kart")[:160]


def _snapshot_card(row, employee) -> str:
    """Store the printed badge (tIdentification), not AxTrax internal iCardCode."""
    if employee is not None and (employee.card_number or "").strip():
        return employee.card_number.strip()[:32]
    code = str(row.get("card_code") or "").strip()
    if code and code != "0":
        return code[:32]
    return ""


@transaction.atomic
def sync_event_rows(
    rows: list,
    *,
    since_id: int | None = None,
    source: str = "export",
    detect_alerts: bool = True,
    advance_cursor: bool = True,
) -> dict:
    """Import already-fetched AxTrax access rows (granted and denied)."""
    live_cursor = get_events_cursor()
    cursor = live_cursor if since_id is None else int(since_id)
    emp_map = _employee_map()
    event_ct = ContentType.objects.get_for_model(AccessEvent)

    stats = {
        "rows_in_file": len(rows),
        "source": source,
        "cursor_before": cursor,
        "created": 0,
        "skipped_existing": 0,
        "skipped_unmapped": 0,
        "skipped_bad_time": 0,
        "skipped_old": 0,
        "rapid_swipe_alerts": 0,
        "shaft_access_alerts": 0,
    }
    max_id = live_cursor
    created_events: list[AccessEvent] = []

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

        result = _access_result(row.get("event_type"))
        employee_pk = emp_map.get(emp_num) if emp_num else None
        employee = None
        if employee_pk:
            employee = ResidentEmployee.objects.filter(pk=employee_pk).only(
                "id", "full_name", "card_number"
            ).first()
        if result == AccessResult.GRANTED and employee is None:
            stats["skipped_unmapped"] += 1
            continue

        occurred_at = _parse_occurred_at(row.get("occurred_at"))
        if not occurred_at:
            stats["skipped_bad_time"] += 1
            continue

        reader_id = None
        if row.get("reader_id") not in (None, ""):
            try:
                reader_id = int(row["reader_id"])
            except (TypeError, ValueError):
                reader_id = None

        event = AccessEvent.objects.create(
            employee_id=employee.pk if employee else None,
            event_type=_event_type(row.get("reader_out")),
            result=result,
            occurred_at=occurred_at,
            employee_name=_snapshot_name(row, employee),
            card_number=_snapshot_card(row, employee),
            axtrax_employee_id=emp_num or None,
            reader_id=reader_id,
            reader_name=(str(row.get("reader_name") or "").strip()[:255]),
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
        if result == AccessResult.GRANTED:
            created_events.append(event)

    if advance_cursor and max_id > live_cursor:
        set_events_cursor(max_id, stats={"created": stats["created"]})
    stats["cursor_after"] = max_id if max_id > live_cursor else live_cursor

    if created_events and detect_alerts:
        from apps.residents.rapid_swipe import detect_rapid_swipes_after_sync
        from apps.residents.shaft_access import detect_shaft_access_after_sync

        alerts = detect_rapid_swipes_after_sync(created_events)
        stats["rapid_swipe_alerts"] = len(alerts)
        shaft_alerts = detect_shaft_access_after_sync(created_events)
        stats["shaft_access_alerts"] = len(shaft_alerts)

    SyncLog.objects.create(
        system=AXTRAX_SYSTEM,
        operation="sync_events",
        status=SyncStatus.SUCCESS,
        request_payload={"source": source, "since_id": cursor, "rows": len(rows)},
        response_payload=stats,
    )
    return stats


def backfill_events_from_date(since_date, *, batch_size: int = 5000) -> dict:
    """Pull AxTrax access-granted events from ``since_date`` (local calendar day) onward.

    Uses ExternalIdentity for dedup so already-imported rows are skipped.
    Does not fire rapid/shaft alerts (historical catch-up).
    """
    from apps.integrations.axtrax_mssql import fetch_granted_events_since

    if hasattr(since_date, "hour"):
        start = since_date
    else:
        start = timezone.make_aware(datetime.combine(since_date, datetime.min.time()))

    after_id = 0
    totals = {
        "batches": 0,
        "rows_fetched": 0,
        "created": 0,
        "skipped_existing": 0,
        "skipped_unmapped": 0,
        "skipped_bad_time": 0,
        "skipped_old": 0,
    }
    while True:
        rows = fetch_granted_events_since(start, after_id=after_id, limit=batch_size)
        if not rows:
            break
        totals["batches"] += 1
        totals["rows_fetched"] += len(rows)
        # since_id=0: do not skip by live poller cursor; ExternalIdentity dedupes.
        stats = sync_event_rows(
            rows,
            since_id=0,
            source=f"backfill:{start.date().isoformat()}",
            detect_alerts=False,
        )
        for key in (
            "created",
            "skipped_existing",
            "skipped_unmapped",
            "skipped_bad_time",
            "skipped_old",
        ):
            totals[key] += int(stats.get(key) or 0)
        after_id = max(int(r["event_id"]) for r in rows)
        if len(rows) < batch_size:
            break
    totals["after_id"] = after_id
    return totals


def backfill_denied_since(since_dt, *, batch_size: int = 5000) -> dict:
    """Import denied access rows (types 18 and 33) even when the live cursor is ahead."""
    from apps.integrations.axtrax_mssql import fetch_denied_events_since

    if not hasattr(since_dt, "hour"):
        since_dt = timezone.make_aware(datetime.combine(since_dt, datetime.min.time()))

    after_id = 0
    totals = {"batches": 0, "rows_fetched": 0, "created": 0, "skipped_existing": 0}
    while True:
        rows = fetch_denied_events_since(since_dt, after_id=after_id, limit=batch_size)
        if not rows:
            break
        totals["batches"] += 1
        totals["rows_fetched"] += len(rows)
        stats = sync_event_rows(
            rows,
            since_id=0,
            source="denied-backfill",
            detect_alerts=False,
            advance_cursor=False,
        )
        totals["created"] += int(stats.get("created") or 0)
        totals["skipped_existing"] += int(stats.get("skipped_existing") or 0)
        after_id = max(int(r["event_id"]) for r in rows)
        if len(rows) < batch_size:
            break
    totals["after_id"] = after_id
    return totals


def sync_events_from_export(path: Path, *, since_id: int | None = None) -> dict:
    payload = load_export(path)
    rows = payload.get("rows") or []
    return sync_event_rows(rows, since_id=since_id, source=str(path))
