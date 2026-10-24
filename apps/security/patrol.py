"""Night floor-patrol sheets. Slot labels are planned rounds; clock times are Baku wall time."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.security.models import (
    FloorPatrolMark,
    FloorPatrolRound,
    FloorPatrolSheet,
    PatrolRoundStatus,
    PatrolSheetStatus,
)

PATROL_FLOOR_CODES = ("-1",) + tuple(str(number) for number in range(1, 14))
PATROL_MARK_ROWS = 7
PATROL_SLOTS = (
    {"code": "20:00", "key": "2000", "day_offset": 0},
    {"code": "22:00", "key": "2200", "day_offset": 0},
    {"code": "00:00", "key": "0000", "day_offset": 1},
    {"code": "02:00", "key": "0200", "day_offset": 1},
    {"code": "04:00", "key": "0400", "day_offset": 1},
    {"code": "06:00", "key": "0600", "day_offset": 1},
)
_SLOT_BY_CODE = {slot["code"]: slot for slot in PATROL_SLOTS}
_SLOT_BY_KEY = {slot["key"]: slot for slot in PATROL_SLOTS}


class PatrolSaveError(Exception):
    def __init__(self, messages):
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


def night_cutoff():
    raw = getattr(settings, "FLOOR_PATROL_NIGHT_CUTOFF", "08:00") or "08:00"
    hour, minute = raw.split(":", 1)
    return time(int(hour), int(minute))


def suggested_night_date(moment=None):
    moment = timezone.localtime(moment or timezone.now())
    if moment.time() < night_cutoff():
        return moment.date() - timedelta(days=1)
    return moment.date()


def round_calendar_date(night_date, slot_code):
    slot = _SLOT_BY_CODE[slot_code]
    return night_date + timedelta(days=slot["day_offset"])


def slot_key(slot_code):
    return _SLOT_BY_CODE[slot_code]["key"]


def clean_floor_codes(codes):
    chosen = []
    for code in codes:
        code = str(code).strip()
        if code in PATROL_FLOOR_CODES and code not in chosen:
            chosen.append(code)
    return [code for code in PATROL_FLOOR_CODES if code in chosen]


def _inspector_index():
    from apps.residents.models import ResidentEmployee

    people = list(
        ResidentEmployee.objects.filter(company__slug="city-point", is_active=True).order_by(
            "full_name"
        )
    )
    by_id = {person.pk: person for person in people}
    by_name = {}
    for person in people:
        by_name.setdefault(person.full_name.casefold(), person)
    return people, by_id, by_name


def citypoint_inspectors():
    people, _by_id, _by_name = _inspector_index()
    return [{"id": person.pk, "name": person.full_name} for person in people]


def inspector_field(raw, index=None):
    """Map a stored name or posted id onto the City Point employee select."""
    raw = (raw or "").strip()
    _people, by_id, by_name = index or _inspector_index()
    if raw.isdigit() and int(raw) in by_id:
        return {"selected": str(int(raw)), "legacy": ""}
    person = by_name.get(raw.casefold())
    if person:
        return {"selected": str(person.pk), "legacy": ""}
    if raw:
        return {"selected": "", "legacy": raw}
    return {"selected": "", "legacy": ""}


def resolve_inspector(raw, *, current="", index=None):
    raw = (raw or "").strip()
    if not raw:
        return ""
    _people, by_id, by_name = index or _inspector_index()
    if raw.isdigit() and int(raw) in by_id:
        return by_id[int(raw)].full_name[:80]
    person = by_name.get(raw.casefold())
    if person:
        return person.full_name[:80]
    if current and raw == current:
        return current[:80]
    raise ValueError("yoxlayan City Point əməkdaşı olmalıdır")


def classify_round(*, started, ended, missed):
    """Return status plus the times that should be stored."""
    if missed:
        return PatrolRoundStatus.MISSED, started, None
    if ended and not started:
        raise ValueError("bitiş başlama olmadan yazıla bilməz")
    if started and ended:
        if started > ended:
            raise ValueError("başlama bitişdən sonra ola bilməz")
        return PatrolRoundStatus.COMPLETED, started, ended
    if started:
        return PatrolRoundStatus.IN_PROGRESS, started, None
    return PatrolRoundStatus.WAITING, None, None


def _parse_clock(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt).time()
            return parsed.replace(microsecond=0)
        except ValueError:
            continue
    raise ValueError("saat formatı səhvdir")


def _clock_text(value):
    if not value:
        return ""
    return value.strftime("%H:%M")


def ensure_sheet_marks(sheet):
    for floor_code in PATROL_FLOOR_CODES:
        for row_index in range(1, PATROL_MARK_ROWS + 1):
            FloorPatrolMark.objects.get_or_create(
                sheet=sheet,
                floor_code=floor_code,
                row_index=row_index,
            )


def _seed_rounds(sheet, floor_codes):
    for floor_code in floor_codes:
        for slot in PATROL_SLOTS:
            FloorPatrolRound.objects.get_or_create(
                sheet=sheet,
                floor_code=floor_code,
                slot=slot["code"],
                defaults={"status": PatrolRoundStatus.WAITING},
            )


def open_or_create_sheet(*, night_date, floor_codes, user):
    floors = clean_floor_codes(floor_codes)
    with transaction.atomic():
        try:
            with transaction.atomic():
                sheet, created = FloorPatrolSheet.objects.get_or_create(
                    night_date=night_date,
                    defaults={
                        "created_by": user,
                        "updated_by": user,
                        "status": PatrolSheetStatus.DRAFT,
                    },
                )
        except IntegrityError:
            sheet = FloorPatrolSheet.objects.get(night_date=night_date)
            created = False
        if created:
            _seed_rounds(sheet, floors)
            ensure_sheet_marks(sheet)
    return sheet, created


def patrolled_floors(sheet):
    present = set(sheet.rounds.values_list("floor_code", flat=True))
    return [code for code in PATROL_FLOOR_CODES if code in present]


def _snapshot(sheet):
    rounds = []
    for rnd in sheet.rounds.all():
        if (
            rnd.status == PatrolRoundStatus.WAITING
            and not rnd.inspector_name
            and not rnd.note
        ):
            continue
        rounds.append(
            {
                "floor": rnd.floor_code,
                "slot": rnd.slot,
                "started": _clock_text(rnd.started_at),
                "ended": _clock_text(rnd.ended_at),
                "status": rnd.status,
                "inspector": rnd.inspector_name,
                "note": rnd.note,
            }
        )
    marks = [
        {"floor": mark.floor_code, "row": mark.row_index, "inspector": mark.inspector_name}
        for mark in sheet.marks.exclude(inspector_name="")
    ]
    return {
        "status": sheet.status,
        "floors": patrolled_floors(sheet),
        "rounds": rounds,
        "marks": marks,
    }


def _sheet_has_content(sheet):
    if sheet.rounds.exclude(status=PatrolRoundStatus.WAITING).exists():
        return True
    return sheet.marks.exclude(inspector_name="").exists()


def _read_posted_rounds(sheet, post, index):
    errors = []
    updates = []
    for rnd in sheet.rounds.all():
        prefix = f"round__{rnd.floor_code}__{slot_key(rnd.slot)}"
        if f"{prefix}__started" not in post and f"{prefix}__inspector" not in post:
            continue
        label = f"Mərtəbə {rnd.floor_code}, tur {rnd.slot}"
        try:
            started = _parse_clock(post.get(f"{prefix}__started"))
            ended = _parse_clock(post.get(f"{prefix}__ended"))
            missed = post.get(f"{prefix}__missed") == "1"
            status, started, ended = classify_round(
                started=started, ended=ended, missed=missed
            )
            inspector = resolve_inspector(
                post.get(f"{prefix}__inspector"),
                current=rnd.inspector_name,
                index=index,
            )
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        updates.append(
            {
                "round": rnd,
                "started": started,
                "ended": ended,
                "status": status,
                "inspector": inspector,
                "note": (post.get(f"{prefix}__note") or "").strip()[:240],
            }
        )
    return updates, errors


def _read_posted_marks(sheet, post, index):
    updates = []
    errors = []
    for mark in sheet.marks.all():
        raw = post.get(f"mark__{mark.floor_code}__{mark.row_index}")
        if raw is None:
            continue
        try:
            inspector = resolve_inspector(raw, current=mark.inspector_name, index=index)
        except ValueError as exc:
            errors.append(
                f"Mərtəbə {mark.floor_code}, YOXLANILDI sətir {mark.row_index}: {exc}"
            )
            continue
        updates.append({"mark": mark, "inspector": inspector})
    return updates, errors


def save_sheet(*, sheet, user, post, action="save", ip_address=None):
    action = action or "save"
    remove_floor = ""
    add_floor = ""
    if action.startswith("remove:"):
        remove_floor = action.split(":", 1)[1]
        action = "remove"
    if action == "add_floor":
        add_floor = (post.get("floor_code") or "").strip()
        if add_floor not in PATROL_FLOOR_CODES:
            raise PatrolSaveError(["Mərtəbə seçilməlidir."])

    with transaction.atomic():
        locked = FloorPatrolSheet.objects.select_for_update().get(pk=sheet.pk)
        ensure_sheet_marks(locked)
        index = _inspector_index()
        updates, errors = _read_posted_rounds(locked, post, index)
        mark_updates, mark_errors = _read_posted_marks(locked, post, index)
        errors.extend(mark_errors)
        if errors:
            raise PatrolSaveError(errors)
        old_status = locked.status
        old_values = _snapshot(locked)
        for item in updates:
            rnd = item["round"]
            rnd.started_at = item["started"]
            rnd.ended_at = item["ended"]
            rnd.status = item["status"]
            rnd.inspector_name = item["inspector"]
            rnd.note = item["note"]
            rnd.save()
        for item in mark_updates:
            mark = item["mark"]
            mark.inspector_name = item["inspector"]
            mark.save(update_fields=["inspector_name"])
        if action == "add_floor":
            _seed_rounds(locked, [add_floor])
        elif action == "remove" and remove_floor:
            locked.rounds.filter(floor_code=remove_floor).delete()

        locked.refresh_from_db()
        if action == "close":
            locked.status = PatrolSheetStatus.CLOSED
        elif action == "reopen":
            locked.status = PatrolSheetStatus.OPEN
        elif locked.status == PatrolSheetStatus.DRAFT and _sheet_has_content(locked):
            locked.status = PatrolSheetStatus.OPEN
        locked.updated_by = user
        locked.save()
        new_values = _snapshot(locked)
        if old_status == PatrolSheetStatus.CLOSED or locked.status == PatrolSheetStatus.CLOSED:
            from apps.audit.services import log_action

            log_action(
                action="floor_patrol.updated",
                actor=user,
                entity=locked,
                old_values=old_values,
                new_values=new_values,
                source="security",
                ip_address=ip_address,
            )
    return FloorPatrolSheet.objects.get(pk=sheet.pk)


def posted_round_rows(sheet, post):
    """Keep typed values on a failed save. Clock strings stay as posted."""
    index = _inspector_index()
    rows = []
    grouped = {code: [] for code in patrolled_floors(sheet)}
    by_floor_slot = {(rnd.floor_code, rnd.slot): rnd for rnd in sheet.rounds.all()}
    for floor_code in grouped:
        for slot in PATROL_SLOTS:
            rnd = by_floor_slot.get((floor_code, slot["code"]))
            if rnd is None:
                continue
            prefix = f"round__{floor_code}__{slot['key']}"
            if post is None:
                started = _clock_text(rnd.started_at)
                ended = _clock_text(rnd.ended_at)
                missed = rnd.status == PatrolRoundStatus.MISSED
                inspector = rnd.inspector_name
                note = rnd.note
                status = rnd.status
            else:
                started = (post.get(f"{prefix}__started") or "").strip()
                ended = (post.get(f"{prefix}__ended") or "").strip()
                missed = post.get(f"{prefix}__missed") == "1"
                inspector = (post.get(f"{prefix}__inspector") or "").strip()
                note = (post.get(f"{prefix}__note") or "").strip()
                status = rnd.status
            choice = inspector_field(inspector, index)
            grouped[floor_code].append(
                {
                    "slot": slot["code"],
                    "date": round_calendar_date(sheet.night_date, slot["code"]),
                    "prefix": prefix,
                    "started": started,
                    "ended": "" if missed else ended,
                    "missed": missed,
                    "inspector": inspector,
                    "inspector_selected": choice["selected"],
                    "inspector_legacy": choice["legacy"],
                    "inspector_field": f"{prefix}__inspector",
                    "note": note,
                    "status": status,
                    "status_label": PatrolRoundStatus(status).label,
                }
            )
    for floor_code, rounds in grouped.items():
        rows.append({"floor": floor_code, "rounds": rounds})
    return rows


def month_check_grid(sheet):
    """One row per day of the sheet's month. X means that floor is on that night's sheet."""
    night = sheet.night_date
    start = night.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    checked = set(
        FloorPatrolRound.objects.filter(
            sheet__night_date__gte=start,
            sheet__night_date__lt=end,
        ).values_list("sheet__night_date", "floor_code")
    )
    rows = []
    day = start
    while day < end:
        rows.append(
            {
                "date": day,
                "current": day == night,
                "cells": [
                    {"floor": code, "checked": (day, code) in checked}
                    for code in PATROL_FLOOR_CODES
                ],
            }
        )
        day += timedelta(days=1)
    return rows


def posted_mark_rows(sheet, post):
    index = _inspector_index()
    marks = {(mark.floor_code, mark.row_index): mark for mark in sheet.marks.all()}
    grid = []
    for row_index in range(1, PATROL_MARK_ROWS + 1):
        cells = []
        for floor_code in PATROL_FLOOR_CODES:
            mark = marks.get((floor_code, row_index))
            key = f"mark__{floor_code}__{row_index}"
            if post is not None and key in post:
                name = post.get(key) or ""
            else:
                name = mark.inspector_name if mark else ""
            choice = inspector_field(name, index)
            cells.append(
                {
                    "floor": floor_code,
                    "row": row_index,
                    "name": name,
                    "inspector_selected": choice["selected"],
                    "inspector_legacy": choice["legacy"],
                    "inspector_field": f"mark__{floor_code}__{row_index}",
                }
            )
        grid.append(cells)
    return grid
