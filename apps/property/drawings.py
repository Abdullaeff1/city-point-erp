"""Space drawing permissions, upload helpers, and access-request workflow."""

from __future__ import annotations

import mimetypes
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.comms.services import notify_in_app
from apps.property.models import (
    SpaceDrawing,
    SpaceDrawingAccessRequest,
    SpaceDrawingAccessStatus,
    SpaceDrawingKind,
)
from apps.security.plan_convert import UnsupportedFormat, convert_source_to_svg

User = get_user_model()

DEFAULT_ACCESS_TTL_HOURS = 72


def user_can_manage_space_drawings(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM}


def drawing_managers_qs():
    return User.objects.filter(
        is_active=True,
        role__in=[Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM],
    )


def _ext_kind(filename: str) -> str | None:
    name = (filename or "").lower()
    if name.endswith(".dxf"):
        return SpaceDrawingKind.DXF
    if name.endswith(".pdf") or name.endswith(".png"):
        return SpaceDrawingKind.TECHNICAL_PLAN
    return None


def try_build_svg(drawing: SpaceDrawing) -> bool:
    """Best-effort DXF→SVG; returns True if svg_file saved."""
    if drawing.kind != SpaceDrawingKind.DXF or not drawing.file:
        return False
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            for chunk in drawing.file.chunks():
                tmp.write(chunk)
        try:
            svg_bytes, _tool, _ver = convert_source_to_svg(tmp_path, "dxf")
        finally:
            tmp_path.unlink(missing_ok=True)
    except (UnsupportedFormat, OSError, Exception):  # noqa: BLE001 — conversion is optional
        return False
    base = Path(drawing.original_name).stem or "drawing"
    drawing.svg_file.save(f"{base}.svg", ContentFile(svg_bytes), save=True)
    return True


@transaction.atomic
def create_space_drawing(
    *,
    space,
    uploaded_file,
    kind: str | None = None,
    uploaded_by=None,
    package_id: str = "",
    build_svg: bool = True,
) -> SpaceDrawing:
    original = getattr(uploaded_file, "name", "") or "file"
    original_name = Path(original).name
    resolved_kind = kind or _ext_kind(original_name)
    if not resolved_kind:
        raise ValueError(_("Yalnız .dxf, .pdf və ya .png qəbul olunur."))
    if resolved_kind == SpaceDrawingKind.DXF and not original_name.lower().endswith(".dxf"):
        raise ValueError(_("DWG tabı üçün yalnız .dxf."))
    if resolved_kind == SpaceDrawingKind.TECHNICAL_PLAN and not (
        original_name.lower().endswith(".pdf") or original_name.lower().endswith(".png")
    ):
        raise ValueError(_("Texniki plan üçün yalnız .pdf və ya .png."))

    ctype = getattr(uploaded_file, "content_type", None) or (
        mimetypes.guess_type(original_name)[0] or ""
    )
    drawing = SpaceDrawing(
        space=space,
        kind=resolved_kind,
        original_name=original_name,
        content_type=ctype,
        uploaded_by=uploaded_by,
        package_id=package_id or "",
    )
    drawing.file.save(original_name, uploaded_file, save=False)
    drawing.full_clean()
    drawing.save()
    if build_svg and resolved_kind == SpaceDrawingKind.DXF:
        try_build_svg(drawing)
    return drawing


@transaction.atomic
def request_drawing_access(*, user, drawing: SpaceDrawing, note: str = "") -> SpaceDrawingAccessRequest:
    pending = SpaceDrawingAccessRequest.objects.filter(
        user=user,
        drawing=drawing,
        status=SpaceDrawingAccessStatus.PENDING,
    ).first()
    if pending:
        return pending
    # Reuse still-valid approval
    active = (
        SpaceDrawingAccessRequest.objects.filter(
            user=user,
            drawing=drawing,
            status=SpaceDrawingAccessStatus.APPROVED,
            expires_at__gt=timezone.now(),
        )
        .order_by("-expires_at")
        .first()
    )
    if active:
        return active

    req = SpaceDrawingAccessRequest.objects.create(
        user=user,
        drawing=drawing,
        note=(note or "")[:255],
    )
    notify_managers_of_access_request(req)
    return req


def notify_managers_of_access_request(req: SpaceDrawingAccessRequest) -> None:
    drawing = req.drawing
    space = drawing.space
    kind_label = drawing.get_kind_display()
    who = req.user.get_full_name().strip() or req.user.email
    message = _(
        "Sahə rəsm icazəsi: %(space)s · %(kind)s · %(file)s — %(who)s"
    ) % {
        "space": space.area_code,
        "kind": kind_label,
        "file": drawing.original_name,
        "who": who,
    }
    event_key = f"space_drawing_access:{req.pk}"
    for manager in drawing_managers_qs():
        notify_in_app(user=manager, message=message[:255], event_key=f"{event_key}:u{manager.pk}")


@transaction.atomic
def decide_access_request(
    *,
    req: SpaceDrawingAccessRequest,
    actor,
    approve: bool,
    ttl_hours: int = DEFAULT_ACCESS_TTL_HOURS,
) -> SpaceDrawingAccessRequest:
    if req.status != SpaceDrawingAccessStatus.PENDING:
        raise ValueError(_("Sorğu artıq cavablanıb."))
    if not user_can_manage_space_drawings(actor):
        raise PermissionError(_("İcazə yoxdur."))
    now = timezone.now()
    req.approved_by = actor
    req.decided_at = now
    if approve:
        req.status = SpaceDrawingAccessStatus.APPROVED
        req.expires_at = now + timedelta(hours=ttl_hours)
        resident_msg = _(
            "Sahə rəsm icazəsi təsdiqləndi: %(space)s · %(file)s (%(hours)s saat)"
        ) % {
            "space": req.drawing.space.area_code,
            "file": req.drawing.original_name,
            "hours": ttl_hours,
        }
    else:
        req.status = SpaceDrawingAccessStatus.DENIED
        req.expires_at = None
        resident_msg = _("Sahə rəsm icazəsi imtina edildi: %(space)s · %(file)s") % {
            "space": req.drawing.space.area_code,
            "file": req.drawing.original_name,
        }
    req.save()
    notify_in_app(
        user=req.user,
        message=resident_msg[:255],
        event_key=f"space_drawing_access_result:{req.pk}",
    )
    return req


def user_may_download_drawing(user, drawing: SpaceDrawing) -> bool:
    if user_can_manage_space_drawings(user):
        return True
    return SpaceDrawingAccessRequest.objects.filter(
        user=user,
        drawing=drawing,
        status=SpaceDrawingAccessStatus.APPROVED,
        expires_at__gt=timezone.now(),
    ).exists()
