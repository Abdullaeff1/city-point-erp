"""Security floor plan domain services."""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import log_action
from apps.core.services import DomainError, Service
from apps.security.access import can_edit_security_plans, device_allowed_on_plan
from apps.security.models import (
    ConversionStatus,
    DeviceStatus,
    SecurityDevice,
    SecurityDevicePin,
    SecurityFloorPlan,
    SecurityFloorPlanRevision,
    SourceFormat,
)
from apps.security.plan_convert import UnsupportedFormat, convert_source_to_svg
from apps.security.svg_sanitize import SvgSanitizeError

logger = logging.getLogger(__name__)

AUDIT_SOURCE = "security_plans"
ALLOWED_EXTENSIONS = {".dwg": SourceFormat.DWG, ".dxf": SourceFormat.DXF}


def _client_ip(request) -> str | None:
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


def _safe_error(msg: str, limit: int = 400) -> str:
    text = " ".join(str(msg).split())
    return text[:limit]


def _file_checksum(uploaded) -> str:
    h = hashlib.sha256()
    for chunk in uploaded.chunks():
        h.update(chunk)
    uploaded.seek(0)
    return h.hexdigest()


def _detect_format(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DomainError("Yalnız .dwg və .dxf fayllarına icazə verilir.")
    return ALLOWED_EXTENSIONS[ext]


def _check_size(uploaded) -> None:
    max_mb = int(getattr(settings, "SECURITY_PLAN_MAX_UPLOAD_MB", 40) or 40)
    size = getattr(uploaded, "size", None)
    if size is not None and size > max_mb * 1024 * 1024:
        raise DomainError(f"Fayl ölçüsü {max_mb} MB limitini aşır.")


def _stored_name(original_name: str, fmt: str) -> str:
    ext = f".{fmt}"
    return f"{uuid.uuid4().hex}{ext}"


class SecurityPlanService(Service):
    @staticmethod
    @transaction.atomic
    def create_plan_with_upload(*, user, title: str, floor, category: str, uploaded, request=None):
        Service.require(can_edit_security_plans(user), "Plan yükləməyə icazəniz yoxdur.")
        Service.require(bool(title and title.strip()), "Başlıq tələb olunur.")
        Service.require(floor is not None, "Mərtəbə tələb olunur.")
        _check_size(uploaded)
        fmt = _detect_format(getattr(uploaded, "name", ""))
        checksum = _file_checksum(uploaded)

        plan = SecurityFloorPlan.objects.create(
            title=title.strip(),
            floor=floor,
            category=category,
            uploaded_by=user,
        )
        rev = SecurityFloorPlanRevision(
            plan=plan,
            revision_number=1,
            source_format=fmt,
            conversion_status=ConversionStatus.PENDING,
            checksum=checksum,
            uploaded_by=user,
        )
        rev.source_file.save(_stored_name(uploaded.name, fmt), uploaded, save=False)
        rev.save()
        log_action(
            action="security_plan.upload",
            actor=user,
            entity=rev,
            new_values={
                "plan_id": plan.pk,
                "revision": 1,
                "format": fmt,
                "checksum": checksum,
            },
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return plan, rev

    @staticmethod
    @transaction.atomic
    def upload_revision(*, user, plan: SecurityFloorPlan, uploaded, request=None):
        Service.require(can_edit_security_plans(user), "Plan yükləməyə icazəniz yoxdur.")
        _check_size(uploaded)
        fmt = _detect_format(getattr(uploaded, "name", ""))
        checksum = _file_checksum(uploaded)
        next_num = (
            plan.revisions.aggregate(m=Max("revision_number")).get("m") or 0
        ) + 1
        rev = SecurityFloorPlanRevision(
            plan=plan,
            revision_number=next_num,
            source_format=fmt,
            conversion_status=ConversionStatus.PENDING,
            checksum=checksum,
            uploaded_by=user,
            is_active=False,
        )
        rev.source_file.save(_stored_name(uploaded.name, fmt), uploaded, save=False)
        rev.save()
        log_action(
            action="security_plan.revision_upload",
            actor=user,
            entity=rev,
            new_values={"plan_id": plan.pk, "revision": next_num, "format": fmt},
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return rev

    @staticmethod
    @transaction.atomic
    def activate_revision(*, user, revision: SecurityFloorPlanRevision, request=None):
        Service.require(can_edit_security_plans(user), "Aktivləşdirməyə icazəniz yoxdur.")
        Service.require(
            revision.conversion_status == ConversionStatus.READY and bool(revision.svg_file),
            "Yalnız hazır (ready) SVG olan revision aktivləşdirilə bilər.",
        )
        plan = revision.plan
        plan.revisions.filter(is_active=True).exclude(pk=revision.pk).update(is_active=False)
        revision.is_active = True
        revision.reviewed_by = user
        revision.reviewed_at = timezone.now()
        revision.save(update_fields=["is_active", "reviewed_by", "reviewed_at"])
        log_action(
            action="security_plan.activate",
            actor=user,
            entity=revision,
            new_values={"plan_id": plan.pk, "revision": revision.revision_number},
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return revision

    @staticmethod
    @transaction.atomic
    def retry_conversion(*, user, revision: SecurityFloorPlanRevision, request=None):
        Service.require(can_edit_security_plans(user), "Yenidən çevirməyə icazəniz yoxdur.")
        Service.require(
            revision.conversion_status
            in {
                ConversionStatus.FAILED,
                ConversionStatus.UNSUPPORTED,
                ConversionStatus.PENDING,
            },
            "Bu revision üçün retry mümkün deyil.",
        )
        revision.conversion_status = ConversionStatus.PENDING
        revision.conversion_error = ""
        revision.save(update_fields=["conversion_status", "conversion_error"])
        log_action(
            action="security_plan.conversion_retry",
            actor=user,
            entity=revision,
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return revision


class SecurityDeviceService(Service):
    @staticmethod
    @transaction.atomic
    def create_device(*, user, name, device_type, ip_address=None, location_note="", request=None):
        Service.require(can_edit_security_plans(user), "Cihaz yaratmağa icazəniz yoxdur.")
        Service.require(bool(name and name.strip()), "Cihaz adı tələb olunur.")
        device = SecurityDevice.objects.create(
            name=name.strip(),
            device_type=device_type,
            ip_address=ip_address or None,
            location_note=(location_note or "").strip(),
            created_by=user,
        )
        log_action(
            action="security_device.create",
            actor=user,
            entity=device,
            new_values={"name": device.name, "type": device.device_type},
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return device

    @staticmethod
    @transaction.atomic
    def update_device(*, user, device: SecurityDevice, **fields):
        Service.require(can_edit_security_plans(user), "Cihaz yeniləməyə icazəniz yoxdur.")
        old = {"name": device.name, "type": device.device_type, "ip": str(device.ip_address or "")}
        for key in ("name", "device_type", "ip_address", "location_note", "status"):
            if key in fields and fields[key] is not None:
                setattr(device, key, fields[key])
        if "name" in fields and fields["name"] is not None:
            device.name = str(fields["name"]).strip()
        device.save()
        log_action(
            action="security_device.update",
            actor=user,
            entity=device,
            old_values=old,
            new_values={
                "name": device.name,
                "type": device.device_type,
                "status": device.status,
            },
            source=AUDIT_SOURCE,
        )
        return device

    @staticmethod
    @transaction.atomic
    def deactivate_device(*, user, device: SecurityDevice, request=None):
        return SecurityDeviceService.update_device(
            user=user, device=device, status=DeviceStatus.INACTIVE
        )


class SecurityPinService(Service):
    @staticmethod
    @transaction.atomic
    def upsert_pin(
        *,
        user,
        revision: SecurityFloorPlanRevision,
        device: SecurityDevice,
        x_pct,
        y_pct,
        note="",
        request=None,
    ):
        Service.require(can_edit_security_plans(user), "Pin yerləşdirməyə icazəniz yoxdur.")
        Service.require(device.is_active, "Yalnız aktiv cihaz pinlənə bilər.")
        Service.require(
            device_allowed_on_plan(revision.plan, device),
            "Bu cihaz tipi plan kateqoriyasına uyğun deyil.",
        )
        x = float(x_pct)
        y = float(y_pct)
        Service.require(0 <= x <= 100 and 0 <= y <= 100, "Koordinatlar 0–100 arası olmalıdır.")
        pin, created = SecurityDevicePin.objects.get_or_create(
            revision=revision,
            device=device,
            defaults={
                "x_pct": x,
                "y_pct": y,
                "note": (note or "").strip(),
                "created_by": user,
                "updated_by": user,
            },
        )
        if not created:
            pin.x_pct = x
            pin.y_pct = y
            if note is not None:
                pin.note = note.strip()
            pin.updated_by = user
            pin.full_clean()
            pin.save()
        else:
            pin.full_clean()
        log_action(
            action="security_pin.create" if created else "security_pin.move",
            actor=user,
            entity=pin,
            new_values={"x": str(pin.x_pct), "y": str(pin.y_pct), "device_id": device.pk},
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )
        return pin, created

    @staticmethod
    @transaction.atomic
    def delete_pin(*, user, pin: SecurityDevicePin, request=None):
        Service.require(can_edit_security_plans(user), "Pin silməyə icazəniz yoxdur.")
        pk = pin.pk
        pin.delete()
        log_action(
            action="security_pin.delete",
            actor=user,
            entity=None,
            old_values={"pin_id": pk},
            source=AUDIT_SOURCE,
            ip_address=_client_ip(request),
        )


def claim_pending_revisions(limit: int = 10):
    """Atomically claim pending revisions for conversion (select_for_update)."""
    with transaction.atomic():
        qs = (
            SecurityFloorPlanRevision.objects.select_for_update(skip_locked=True)
            .filter(conversion_status=ConversionStatus.PENDING)
            .order_by("id")[:limit]
        )
        claimed = list(qs)
        for rev in claimed:
            rev.conversion_status = ConversionStatus.PROCESSING
            rev.conversion_error = ""
            rev.save(update_fields=["conversion_status", "conversion_error"])
        return claimed


def convert_revision(revision: SecurityFloorPlanRevision) -> str:
    """Convert one revision; returns final status string."""
    path = Path(revision.source_file.path)
    try:
        svg_bytes, tool, version = convert_source_to_svg(path, revision.source_format)
    except UnsupportedFormat as exc:
        revision.conversion_status = ConversionStatus.UNSUPPORTED
        revision.conversion_error = _safe_error(exc)
        revision.save(
            update_fields=["conversion_status", "conversion_error"]
        )
        return ConversionStatus.UNSUPPORTED
    except SvgSanitizeError as exc:
        logger.warning("security plan SVG sanitize failed revision=%s: %s", revision.pk, exc)
        revision.conversion_status = ConversionStatus.FAILED
        revision.conversion_error = _safe_error(exc)
        revision.save(update_fields=["conversion_status", "conversion_error"])
        return ConversionStatus.FAILED
    except Exception as exc:  # noqa: BLE001
        logger.exception("security plan conversion failed revision=%s", revision.pk)
        revision.conversion_status = ConversionStatus.FAILED
        revision.conversion_error = _safe_error("Conversion uğursuz oldu.")
        revision.save(update_fields=["conversion_status", "conversion_error"])
        return ConversionStatus.FAILED

    max_svg = 15 * 1024 * 1024
    if len(svg_bytes) > max_svg:
        revision.conversion_status = ConversionStatus.FAILED
        revision.conversion_error = "SVG çıxışı həddən böyükdür."
        revision.save(update_fields=["conversion_status", "conversion_error"])
        return ConversionStatus.FAILED

    name = f"{uuid.uuid4().hex}.svg"
    revision.svg_file.save(name, ContentFile(svg_bytes), save=False)
    revision.conversion_status = ConversionStatus.READY
    revision.conversion_error = ""
    revision.conversion_tool = tool
    revision.conversion_version = version
    revision.converted_at = timezone.now()
    revision.save()
    return ConversionStatus.READY


def log_download(*, user, revision, kind: str, request=None):
    log_action(
        action=f"security_plan.download_{kind}",
        actor=user,
        entity=revision,
        new_values={"plan_id": revision.plan_id, "revision": revision.revision_number},
        source=AUDIT_SOURCE,
        ip_address=_client_ip(request),
    )
