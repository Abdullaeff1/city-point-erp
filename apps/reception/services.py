import secrets

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.services import DomainError, Service
from apps.reception.models import (
    Guest,
    GuestVisit,
    VisitStatus,
    VisitorAccess,
    VisitorAccessStatus,
    SyncStatus,
    normalize_fin,
)


def new_invite_code() -> str:
    return secrets.token_urlsafe(8)[:12].upper()


def _audit(action: str, actor=None, entity=None, old=None, new=None):
    try:
        from apps.audit.services import log_action

        log_action(
            action=action,
            actor=actor,
            entity=entity,
            old_values=old,
            new_values=new,
            source="reception",
        )
    except Exception:
        pass


class ReceptionService(Service):
    @staticmethod
    def find_guest_by_fin(fin: str):
        code = normalize_fin(fin)
        if not code:
            return None
        return Guest.objects.filter(fin_code=code, is_active=True).first()

    @classmethod
    def find_or_create_guest(
        cls,
        *,
        fin_code: str,
        first_name: str,
        last_name: str,
        phone: str = "",
        email: str = "",
        actor=None,
    ) -> Guest:
        fin = normalize_fin(fin_code)
        first = (first_name or "").strip()
        last = (last_name or "").strip()
        cls.require(bool(first and last), "Ad və soyad tələb olunur.")
        guest = cls.find_guest_by_fin(fin) if fin else None
        if guest:
            changed = False
            if first and guest.first_name != first:
                guest.first_name = first
                changed = True
            if last and guest.last_name != last:
                guest.last_name = last
                changed = True
            if phone and not guest.phone:
                guest.phone = phone
                changed = True
            if email and not guest.email:
                guest.email = email
                changed = True
            if changed:
                guest.full_name = f"{guest.first_name} {guest.last_name}".strip()
                guest.save()
                _audit("guest.updated", actor=actor, entity=guest)
            return guest
        guest = Guest.objects.create(
            fin_code=fin,
            first_name=first,
            last_name=last,
            full_name=f"{first} {last}".strip(),
            phone=phone or "",
            email=email or "",
        )
        _audit("guest.created", actor=actor, entity=guest, new={"fin_masked": True})
        return guest

    @classmethod
    @transaction.atomic
    def register_walk_in(
        cls,
        *,
        fin_code: str,
        first_name: str,
        last_name: str,
        company,
        host=None,
        visit_type=None,
        id_document_held: bool = False,
        id_override_reason: str = "",
        notes: str = "",
        phone: str = "",
        actor=None,
        allow_id_override: bool = False,
    ) -> GuestVisit:
        cls.require(company is not None, "Şirkət seçilməlidir.")
        cls.require(bool(normalize_fin(fin_code)), "FIN tələb olunur.")
        if not id_document_held:
            cls.require(
                allow_id_override and bool(id_override_reason.strip()),
                "Şəxsiyyət vəsiqəsi qəbul edilməlidir (və ya override + səbəb).",
            )
        if host is not None:
            cls.require(host.company_id == company.id, "Host seçilmiş şirkətə aid deyil.")
            cls.require(host.is_active, "Host aktiv deyil.")

        guest = cls.find_or_create_guest(
            fin_code=fin_code,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            actor=actor,
        )
        active = (
            GuestVisit.objects.select_for_update()
            .filter(guest=guest, status=VisitStatus.INSIDE)
            .first()
        )
        cls.require(active is None, "Bu qonaq artıq binadadır (Inside).")

        now = timezone.now()
        visit = GuestVisit.objects.create(
            guest=guest,
            company=company,
            host=host,
            visit_type=visit_type,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=now,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
            id_document_held=bool(id_document_held),
            id_override_reason=id_override_reason.strip() if not id_document_held else "",
            notes=notes or "",
            pre_registered=False,
        )
        create_visitor_access(visit)
        _audit(
            "visit.check_in",
            actor=actor,
            entity=visit,
            new={"status": visit.status, "id_held": visit.id_document_held},
        )
        return visit

    @classmethod
    @transaction.atomic
    def check_in_visit(
        cls,
        visit: GuestVisit,
        *,
        actor=None,
        fin_code: str = "",
        id_document_held: bool = False,
        id_override_reason: str = "",
        allow_id_override: bool = False,
        first_name: str = "",
        last_name: str = "",
    ) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().select_related("guest").get(pk=visit.pk)
        cls.require(visit.status != VisitStatus.CANCELLED, "Ləğv olunmuş ziyarət check-in edilə bilməz.")
        cls.require(
            visit.status in (VisitStatus.PRE_REGISTERED, VisitStatus.WAITING),
            "Bu ziyarət check-in üçün uyğun deyil.",
        )
        if not id_document_held:
            cls.require(
                allow_id_override and bool(id_override_reason.strip()),
                "Şəxsiyyət vəsiqəsi qəbul edilməlidir.",
            )
        guest = visit.guest
        if fin_code:
            guest.fin_code = normalize_fin(fin_code)
        if first_name:
            guest.first_name = first_name.strip()
        if last_name:
            guest.last_name = last_name.strip()
        if first_name or last_name or fin_code:
            guest.full_name = f"{guest.first_name} {guest.last_name}".strip() or guest.full_name
            guest.save()

        other = (
            GuestVisit.objects.select_for_update()
            .filter(guest=guest, status=VisitStatus.INSIDE)
            .exclude(pk=visit.pk)
            .exists()
        )
        cls.require(not other, "Bu qonaq artıq binadadır.")

        visit.status = VisitStatus.INSIDE
        visit.check_in_at = timezone.now()
        visit.id_document_held = bool(id_document_held)
        if not id_document_held:
            visit.id_override_reason = id_override_reason.strip()
        visit.save(
            update_fields=[
                "status",
                "check_in_at",
                "id_document_held",
                "id_override_reason",
                "updated_at",
            ]
        )
        create_visitor_access(visit)
        _audit("visit.check_in", actor=actor, entity=visit)
        return visit

    @classmethod
    @transaction.atomic
    def check_out_visit(
        cls,
        visit: GuestVisit,
        *,
        actor=None,
        id_returned: bool = True,
        allow_return_pending: bool = False,
    ) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().get(pk=visit.pk)
        cls.require(visit.status == VisitStatus.INSIDE, "Yalnız içəridə olan qonaq çıxış edə bilər.")
        now = timezone.now()
        if visit.check_in_at and now < visit.check_in_at:
            raise DomainError("Çıxış vaxtı girişdən əvvəl ola bilməz.")

        if visit.id_document_held and not id_returned:
            cls.require(allow_return_pending, "Vəsiqə qaytarılmalıdır.")
            visit.status = VisitStatus.RETURN_PENDING
            visit.check_out_at = now
            visit.save(update_fields=["status", "check_out_at", "updated_at"])
            revoke_visitor_access(visit)
            _audit("visit.return_pending", actor=actor, entity=visit)
            return visit

        visit.status = VisitStatus.LEFT
        visit.check_out_at = now
        if visit.id_document_held or id_returned:
            visit.id_document_held = False
            visit.id_document_returned_at = now
        visit.save(
            update_fields=[
                "status",
                "check_out_at",
                "id_document_held",
                "id_document_returned_at",
                "updated_at",
            ]
        )
        revoke_visitor_access(visit)
        _audit("visit.check_out", actor=actor, entity=visit)
        return visit

    @classmethod
    @transaction.atomic
    def cancel_visit(cls, visit: GuestVisit, *, actor=None) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().get(pk=visit.pk)
        cls.require(
            visit.status in (VisitStatus.PRE_REGISTERED, VisitStatus.WAITING),
            "Bu statusda ləğv edilə bilməz.",
        )
        visit.status = VisitStatus.CANCELLED
        visit.save(update_fields=["status", "updated_at"])
        _audit("visit.cancelled", actor=actor, entity=visit)
        return visit

    @classmethod
    @transaction.atomic
    def mark_no_show(cls, visit: GuestVisit, *, actor=None) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().get(pk=visit.pk)
        cls.require(visit.status == VisitStatus.PRE_REGISTERED, "Yalnız pre-reg no-show ola bilər.")
        visit.status = VisitStatus.NO_SHOW
        visit.save(update_fields=["status", "updated_at"])
        _audit("visit.no_show", actor=actor, entity=visit)
        return visit


@transaction.atomic
def pre_register_visit(
    *,
    company,
    full_name: str = "",
    first_name: str = "",
    last_name: str = "",
    host=None,
    space=None,
    floor=None,
    scheduled_for=None,
    email: str = "",
    phone: str = "",
    portal_user=None,
    location_note: str = "",
    visit_type=None,
) -> GuestVisit:
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not first and full_name:
        parts = full_name.strip().split(None, 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
    guest = Guest.objects.create(
        first_name=first,
        last_name=last,
        full_name=f"{first} {last}".strip() or full_name.strip(),
        email=email or "",
        phone=phone or "",
    )
    if host is not None and host.company_id != company.id:
        raise DomainError("Host seçilmiş şirkətə aid deyil.")
    return GuestVisit.objects.create(
        guest=guest,
        company=company,
        host=host,
        visit_type=visit_type,
        space=space,
        floor=floor or (space.floor if space else None),
        location_note=location_note,
        status=VisitStatus.PRE_REGISTERED,
        scheduled_for=scheduled_for or timezone.localdate(),
        pre_registered=True,
        invite_code=new_invite_code(),
        created_by_portal_user=portal_user,
        created_by=portal_user,
    )


def check_in_visit(visit: GuestVisit, **kwargs) -> GuestVisit:
    return ReceptionService.check_in_visit(visit, **kwargs)


def check_out_visit(visit: GuestVisit, **kwargs) -> GuestVisit:
    return ReceptionService.check_out_visit(visit, **kwargs)


def create_visitor_access(visit: GuestVisit) -> VisitorAccess:
    access, _ = VisitorAccess.objects.get_or_create(
        visit=visit,
        defaults={
            "provider": "mock",
            "status": VisitorAccessStatus.PENDING,
            "sync_status": SyncStatus.PENDING,
            "valid_from": visit.check_in_at or timezone.now(),
        },
    )
    try:
        from apps.integrations.adapters import MockAccessControlAdapter

        result = MockAccessControlAdapter().assign_credential(
            {"code": visit.invite_code or f"visit-{visit.pk}", "visit_id": visit.pk}
        )
        access.external_id = result.external_id or access.external_id
        access.status = VisitorAccessStatus.ACTIVE if result.ok else VisitorAccessStatus.FAILED
        access.sync_status = SyncStatus.SUCCESS if result.ok else SyncStatus.ERROR
        access.last_error = result.error or ""
        access.last_sync_at = timezone.now()
        access.save()
    except Exception as exc:
        access.status = VisitorAccessStatus.FAILED
        access.sync_status = SyncStatus.ERROR
        access.last_error = str(exc)
        access.last_sync_at = timezone.now()
        access.save()
    return access


def revoke_visitor_access(visit: GuestVisit) -> None:
    access = getattr(visit, "visitor_access", None)
    if not access:
        return
    try:
        from apps.integrations.adapters import MockAccessControlAdapter

        MockAccessControlAdapter().revoke_credential({"code": access.external_id or access.credential})
        access.status = VisitorAccessStatus.REVOKED
        access.sync_status = SyncStatus.SUCCESS
        access.last_sync_at = timezone.now()
        access.last_error = ""
        access.save()
    except Exception as exc:
        access.sync_status = SyncStatus.ERROR
        access.last_error = str(exc)
        access.last_sync_at = timezone.now()
        access.save()


def today_visits_queryset(day=None):
    day = day or timezone.localdate()
    return GuestVisit.objects.filter(scheduled_for=day).select_related(
        "guest", "company", "host", "visit_type", "visitor_access"
    )


def filter_visits(qs, *, q="", status="", company_id=None, id_not_returned=False):
    if q:
        qn = q.strip()
        qs = qs.filter(
            Q(guest__fin_code__icontains=normalize_fin(qn))
            | Q(guest__first_name__icontains=qn)
            | Q(guest__last_name__icontains=qn)
            | Q(guest__full_name__icontains=qn)
            | Q(company__name__icontains=qn)
            | Q(host__full_name__icontains=qn)
            | Q(invite_code__icontains=qn)
        )
    if status == "inside":
        qs = qs.filter(status=VisitStatus.INSIDE)
    elif status == "checked_out":
        qs = qs.filter(status=VisitStatus.LEFT)
    elif status == "pre_registered":
        qs = qs.filter(status=VisitStatus.PRE_REGISTERED)
    elif status == "cancelled":
        qs = qs.filter(status=VisitStatus.CANCELLED)
    elif status == "no_show":
        qs = qs.filter(status=VisitStatus.NO_SHOW)
    elif status == "waiting":
        qs = qs.filter(status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED])
    if company_id:
        qs = qs.filter(company_id=company_id)
    if id_not_returned:
        qs = qs.filter(
            Q(status=VisitStatus.RETURN_PENDING)
            | Q(id_document_held=True, status=VisitStatus.LEFT, id_document_returned_at__isnull=True)
            | Q(id_document_held=True, status=VisitStatus.INSIDE)
        )
    return qs
