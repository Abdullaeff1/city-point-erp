import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.search import filter_text_search
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


# Visit types that may enter without ID held / seriya (no override required).
ID_OPTIONAL_VISIT_CODES = frozenset({"courier"})


def id_policy_skips_document(*, visit_type=None, list_import_id=None) -> bool:
    """Guest-list import and courier-style visits may skip ID hold."""
    if list_import_id:
        return True
    code = getattr(visit_type, "code", None) or ""
    return code in ID_OPTIONAL_VISIT_CODES


def _audit(action: str, actor=None, entity=None, old=None, new=None):
    try:
        from apps.audit.services import log_action

        payload = dict(new or {})
        if entity is not None:
            guest = getattr(entity, "guest", None)
            if guest is not None:
                payload.setdefault("guest", str(guest))
            elif entity.__class__.__name__ == "Guest":
                payload.setdefault("guest", str(entity))
            company = getattr(entity, "company", None)
            if company is not None:
                payload.setdefault("company", str(company))
        log_action(
            action=action,
            actor=actor,
            entity=entity,
            old_values=old,
            new_values=payload or None,
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
        guest_card_number: str = "",
    ) -> GuestVisit:
        cls.require(company is not None, "Şirkət seçilməlidir.")
        held = bool(id_document_held)
        card = normalize_guest_card(guest_card_number)
        fin = normalize_fin(fin_code)
        reason = (id_override_reason or "").strip()
        # Vəsiqə məcburi deyil; qonaq kartı veriləndə vəsiqə + seriya lazımdır.
        if card and not held:
            cls.require(False, "Qonaq kartı üçün vəsiqə qəbul olunmalıdır.")
        if held:
            cls.require(bool(fin), "Seriya nömrəsi tələb olunur.")
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
            id_document_held=held,
            id_override_reason=(reason if (not held and reason) else ""),
            notes=notes or "",
            pre_registered=False,
        )
        if card:
            create_visitor_access(visit, credential=card)
        _audit(
            "visit.check_in",
            actor=actor,
            entity=visit,
            new={"status": visit.status, "id_held": visit.id_document_held, "card": bool(card)},
        )
        from apps.core import events as bus

        bus.emit(
            bus.VISITOR_CHECKED_IN,
            payload={"visit_id": visit.pk, "company_id": visit.company_id, "entity_model": "visit"},
            actor=actor,
            event_key=f"visitor.checked_in.{visit.pk}",
        )
        return visit

    @classmethod
    @transaction.atomic
    def update_visit_details(
        cls,
        visit: GuestVisit,
        *,
        fin_code: str = "",
        first_name: str = "",
        last_name: str = "",
        company,
        host=None,
        visit_type=None,
        id_document_held: bool = False,
        guest_card_number: str = "",
        notes: str = "",
        actor=None,
    ) -> GuestVisit:
        """Correct guest details. Check-in and check-out times stay as recorded."""
        visit = GuestVisit.objects.select_for_update().select_related("guest").get(pk=visit.pk)
        cls.require(visit.status != VisitStatus.CANCELLED, "Ləğv olunmuş ziyarət dəyişdirilə bilməz.")
        held = bool(id_document_held)
        card = normalize_guest_card(guest_card_number)
        fin = normalize_fin(fin_code)
        first = (first_name or "").strip()
        last = (last_name or "").strip()
        cls.require(bool(first and last), "Ad və soyad tələb olunur.")
        cls.require(company is not None, "Şirkət seçilməlidir.")
        if held:
            cls.require(bool(fin), "Seriya nömrəsi tələb olunur.")
        if host is not None:
            cls.require(host.company_id == company.id, "Host seçilmiş şirkətə aid deyil.")
            cls.require(host.is_active, "Host aktiv deyil.")

        guest = visit.guest
        if fin:
            taken = Guest.objects.filter(fin_code=fin, is_active=True).exclude(pk=guest.pk).exists()
            cls.require(not taken, "Bu seriya nömrəsi başqa qonağa aiddir.")
        guest.fin_code = fin
        guest.first_name = first
        guest.last_name = last
        guest.full_name = f"{first} {last}".strip()
        guest.save()

        visit.company = company
        visit.host = host
        visit.visit_type = visit_type
        visit.id_document_held = held
        visit.notes = notes or ""
        if held:
            visit.id_override_reason = ""
        visit.save(
            update_fields=[
                "company",
                "host",
                "visit_type",
                "id_document_held",
                "notes",
                "id_override_reason",
                "updated_at",
            ]
        )
        if card:
            create_visitor_access(visit, credential=card)
        else:
            access = VisitorAccess.objects.filter(visit=visit).first()
            if access and access.credential:
                access.credential = ""
                access.save(update_fields=["credential"])
        _audit(
            "visit.updated",
            actor=actor,
            entity=visit,
            new={"id_held": visit.id_document_held, "card": bool(card)},
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
        guest_card_number: str = "",
    ) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().select_related("guest").get(pk=visit.pk)
        cls.require(visit.status != VisitStatus.CANCELLED, "Ləğv olunmuş ziyarət check-in edilə bilməz.")
        cls.require(
            visit.status in (VisitStatus.PRE_REGISTERED, VisitStatus.WAITING),
            "Bu ziyarət check-in üçün uyğun deyil.",
        )
        held = bool(id_document_held)
        card = normalize_guest_card(guest_card_number)
        reason = (id_override_reason or "").strip()
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

        fin = normalize_fin(guest.fin_code)
        if card and not held:
            cls.require(False, "Qonaq kartı üçün vəsiqə qəbul olunmalıdır.")
        if held:
            cls.require(bool(fin), "Seriya nömrəsi tələb olunur.")

        other = (
            GuestVisit.objects.select_for_update()
            .filter(guest=guest, status=VisitStatus.INSIDE)
            .exclude(pk=visit.pk)
            .exists()
        )
        cls.require(not other, "Bu qonaq artıq binadadır.")

        visit.status = VisitStatus.INSIDE
        visit.check_in_at = timezone.now()
        visit.id_document_held = held
        visit.id_override_reason = reason if (not held and reason) else ""
        visit.save(
            update_fields=[
                "status",
                "check_in_at",
                "id_document_held",
                "id_override_reason",
                "updated_at",
            ]
        )
        if card:
            create_visitor_access(visit, credential=card)
        _audit("visit.check_in", actor=actor, entity=visit)
        from apps.core import events as bus

        bus.emit(
            bus.VISITOR_CHECKED_IN,
            payload={"visit_id": visit.pk, "company_id": visit.company_id, "entity_model": "visit"},
            actor=actor,
            event_key=f"visitor.checked_in.{visit.pk}",
        )
        return visit

    @classmethod
    @transaction.atomic
    def check_in_list(cls, list_import, *, actor=None) -> int:
        """Check in every still-waiting guest from one uploaded list. No ID is taken."""
        visits = list(
            GuestVisit.objects.select_for_update()
            .filter(
                list_import=list_import,
                status__in=(VisitStatus.PRE_REGISTERED, VisitStatus.WAITING),
            )
            .order_by("pk")
        )
        for visit in visits:
            cls.check_in_visit(visit, actor=actor, id_document_held=False)
        return len(visits)

    @classmethod
    def _resolve_departure_stamps(cls, visit: GuestVisit, *, departed_at, now):
        """Validate optional known departure; always stamp administrative close time.

        ``actual_departure_at`` is null when the operator does not know exit time.
        ``check_out_recorded_at`` is always the close action time.
        ``check_out_at`` remains the display/export exit stamp (known departure or close).
        """
        if departed_at is not None:
            stamp = departed_at
            if timezone.is_naive(stamp):
                stamp = timezone.make_aware(stamp, timezone.get_current_timezone())
            if visit.check_in_at and stamp < visit.check_in_at:
                raise DomainError("Çıxış vaxtı girişdən əvvəl ola bilməz.")
            if stamp > now:
                raise DomainError("Çıxış vaxtı gələcək ola bilməz.")
            return stamp, stamp, now
        return None, now, now

    @classmethod
    @transaction.atomic
    def check_out_visit(
        cls,
        visit: GuestVisit,
        *,
        actor=None,
        id_returned: bool = True,
        allow_return_pending: bool = False,
        departed_at=None,
        checkout_source: str = "",
        access_event_id=None,
    ) -> GuestVisit:
        visit = GuestVisit.objects.select_for_update().get(pk=visit.pk)
        cls.require(visit.status == VisitStatus.INSIDE, "Yalnız içəridə olan qonaq çıxış edə bilər.")
        now = timezone.now()
        actual_departure, display_stamp, recorded_at = cls._resolve_departure_stamps(
            visit, departed_at=departed_at, now=now
        )
        source = (checkout_source or ("axtrax_out" if access_event_id else "manual")).strip()
        audit_extra = {
            "checkout_source": source,
            "access_event_id": access_event_id,
            "departed_at": actual_departure.isoformat() if actual_departure else None,
            "departure_known": actual_departure is not None,
            "processed_at": recorded_at.isoformat(),
            "actor_id": getattr(actor, "pk", None),
        }

        if visit.id_document_held and not id_returned:
            cls.require(allow_return_pending, "Vəsiqə qaytarılmalıdır.")
            visit.status = VisitStatus.RETURN_PENDING
            visit.check_out_at = display_stamp
            visit.actual_departure_at = actual_departure
            visit.check_out_recorded_at = recorded_at
            visit.save(
                update_fields=[
                    "status",
                    "check_out_at",
                    "actual_departure_at",
                    "check_out_recorded_at",
                    "updated_at",
                ]
            )
            revoke_visitor_access(visit, until=display_stamp)
            _audit("visit.return_pending", actor=actor, entity=visit, new=audit_extra)
            from apps.core import events as bus

            bus.emit(
                bus.VISITOR_RETURN_PENDING,
                payload={
                    "visit_id": visit.pk,
                    "company_id": visit.company_id,
                    "entity_model": "visit",
                    "reason": "id_held",
                    "checkout_source": source,
                    "access_event_id": access_event_id,
                    "departed_at": actual_departure.isoformat() if actual_departure else None,
                    "processed_at": recorded_at.isoformat(),
                    # Never put ID document numbers in event/notify payloads.
                    "id_document_held": True,
                },
                actor=actor,
                event_key=f"visitor.return_pending.{visit.pk}",
            )
            return visit

        visit.status = VisitStatus.LEFT
        visit.check_out_at = display_stamp
        visit.actual_departure_at = actual_departure
        visit.check_out_recorded_at = recorded_at
        if visit.id_document_held or id_returned:
            visit.id_document_held = False
            visit.id_document_returned_at = recorded_at
        visit.save(
            update_fields=[
                "status",
                "check_out_at",
                "actual_departure_at",
                "check_out_recorded_at",
                "id_document_held",
                "id_document_returned_at",
                "updated_at",
            ]
        )
        revoke_visitor_access(visit, until=display_stamp)
        _audit("visit.check_out", actor=actor, entity=visit, new=audit_extra)
        from apps.core import events as bus

        bus.emit(
            bus.VISITOR_CHECKED_OUT,
            payload={
                "visit_id": visit.pk,
                "company_id": visit.company_id,
                "entity_model": "visit",
                "id_returned": bool(id_returned or not visit.id_document_held),
                "checkout_source": source,
                "access_event_id": access_event_id,
                "departed_at": actual_departure.isoformat() if actual_departure else None,
                "processed_at": recorded_at.isoformat(),
            },
            actor=actor,
            event_key=f"visitor.checked_out.{visit.pk}",
        )
        return visit

    @classmethod
    @transaction.atomic
    def complete_id_return(cls, visit: GuestVisit, *, actor=None) -> GuestVisit:
        """Reception completes document return after AxTrax/manual RETURN_PENDING."""
        visit = GuestVisit.objects.select_for_update().get(pk=visit.pk)
        cls.require(
            visit.status == VisitStatus.RETURN_PENDING,
            "Yalnız vəsiqə gözləyən ziyarət tamamlana bilər.",
        )
        now = timezone.now()
        visit.status = VisitStatus.LEFT
        visit.id_document_held = False
        visit.id_document_returned_at = now
        if not visit.check_out_at:
            visit.check_out_at = now
        if not visit.check_out_recorded_at:
            visit.check_out_recorded_at = now
        visit.save(
            update_fields=[
                "status",
                "id_document_held",
                "id_document_returned_at",
                "check_out_at",
                "check_out_recorded_at",
                "updated_at",
            ]
        )
        _audit("visit.id_returned", actor=actor, entity=visit)
        from apps.core import events as bus

        bus.emit(
            bus.VISITOR_CHECKED_OUT,
            payload={
                "visit_id": visit.pk,
                "company_id": visit.company_id,
                "entity_model": "visit",
                "id_returned": True,
                "completion": "id_return",
            },
            actor=actor,
            event_key=f"visitor.id_returned.{visit.pk}",
        )
        return visit

    @classmethod
    def check_out_visits(cls, visits, *, actor=None) -> int:
        """Check out every still-inside visit. Held IDs are marked returned."""
        pks = [visit.pk for visit in visits]
        count = 0
        with transaction.atomic():
            for pk in pks:
                visit = GuestVisit.objects.get(pk=pk)
                if visit.status != VisitStatus.INSIDE:
                    continue
                cls.check_out_visit(visit, actor=actor, id_returned=True)
                count += 1
        return count

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
    if host is not None:
        if host.company_id != company.id:
            raise DomainError("Host seçilmiş şirkətə aid deyil.")
        if not host.is_active:
            raise DomainError("Host aktiv deyil.")
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


def complete_id_return(visit: GuestVisit, **kwargs) -> GuestVisit:
    return ReceptionService.complete_id_return(visit, **kwargs)


def normalize_guest_card(value: str) -> str:
    """Store/match guest card as a string — preserve leading zeros (no int cast)."""
    return (value or "").strip()


def guest_card_match_keys(value: str) -> set[str]:
    """Exact form plus zero-stripped form so AxTrax ``7`` matches stored ``007``."""
    code = normalize_guest_card(value)
    if not code:
        return set()
    keys = {code}
    stripped = code.lstrip("0") or "0"
    keys.add(stripped)
    return keys


def visit_has_active_guest_card(visit: GuestVisit) -> bool:
    try:
        access = visit.visitor_access
    except VisitorAccess.DoesNotExist:
        return False
    return access.status == VisitorAccessStatus.ACTIVE


def can_portal_checkout(visit: GuestVisit, *, company) -> bool:
    """Resident may close admitted cardless visits when Reception holds no ID document.

    Includes Reception walk-ins without ID/card. Card-issued visits stay Reception-owned.
    """
    if company is None or visit.company_id != company.id:
        return False
    if visit.status != VisitStatus.INSIDE:
        return False
    if visit.id_document_held:
        return False
    if visit_has_active_guest_card(visit):
        return False
    return True


def is_portal_checkout_overdue(visit: GuestVisit, *, now=None) -> bool:
    """True when an eligible cardless INSIDE visit passed check-in + 24h."""
    if visit.status != VisitStatus.INSIDE:
        return False
    if visit.id_document_held or visit_has_active_guest_card(visit):
        return False
    now = now or timezone.now()
    start = visit.check_in_at or visit.created_at
    if start is None:
        return False
    return start <= now - timedelta(hours=24)


def portal_cardless_overdue_queryset(*, now=None):
    """Open cardless visits past the 24h check-in boundary (portal alert candidates)."""
    cutoff = (now or timezone.now()) - timedelta(hours=24)
    return (
        GuestVisit.objects.filter(status=VisitStatus.INSIDE, id_document_held=False)
        .filter(
            Q(check_in_at__lte=cutoff)
            | Q(check_in_at__isnull=True, created_at__lte=cutoff)
        )
        .exclude(visitor_access__status=VisitorAccessStatus.ACTIVE)
        .select_related("guest", "company")
        .order_by("check_in_at", "id")
    )


def portal_guest_alert_recipients(company):
    """In-app overdue recipients for a company.

    Policy (no finer guest-mgmt PermissionCode in catalog): every active
    ``PortalCompanyMembership`` for a ``RESIDENT_USER`` on that company — the
    same population that can open the portal guest list / cardless checkout.
    """
    from django.contrib.auth import get_user_model

    from apps.accounts.models import PortalCompanyMembership, Role

    User = get_user_model()
    if company is None:
        return User.objects.none()
    user_ids = PortalCompanyMembership.objects.filter(
        company_id=company.pk if hasattr(company, "pk") else company,
        is_active=True,
        user__role=Role.RESIDENT_USER,
        user__is_active=True,
    ).values_list("user_id", flat=True)
    return User.objects.filter(pk__in=user_ids).order_by("pk")


OVERDUE_CHECKOUT_EVENT_PREFIX = "visitor.checkout_overdue."


def overdue_checkout_event_key(visit_id: int, user_id: int) -> str:
    return f"{OVERDUE_CHECKOUT_EVENT_PREFIX}{visit_id}.u.{user_id}"


def notify_portal_checkout_overdue(visit: GuestVisit) -> int:
    """One in-app alert per authorized recipient × visit (idempotent via event_key)."""
    from apps.comms.models import Notification
    from apps.comms.services import notify_in_app

    if not is_portal_checkout_overdue(visit):
        return 0
    label = visit.guest.display_name if visit.guest_id else str(visit.pk)
    created = 0
    for user in portal_guest_alert_recipients(visit.company):
        key = overdue_checkout_event_key(visit.pk, user.pk)
        existed = Notification.objects.filter(user=user, event_key=key).exists()
        note = notify_in_app(
            user=user,
            message=f"Qonaq çıxışı gecikir (24 saat+): {label}",
            event_key=key,
        )
        if note is not None and not existed:
            created += 1
    return created


def process_portal_checkout_overdue_alerts(*, now=None) -> dict:
    """Scheduler body: cardless portal overdue only; safe to re-run."""
    now = now or timezone.now()
    visits = list(portal_cardless_overdue_queryset(now=now))
    created = 0
    for visit in visits:
        created += notify_portal_checkout_overdue(visit)
    return {
        "visits": len(visits),
        "notifications_created": created,
        "as_of": now.isoformat(),
        "kind": "portal_cardless",
    }


def is_id_held_inside_overdue(visit: GuestVisit, *, now=None) -> bool:
    """True when visit is still INSIDE with ID held past check-in + 24h (inclusive boundary)."""
    if visit.status != VisitStatus.INSIDE:
        return False
    if not visit.id_document_held:
        return False
    now = now or timezone.now()
    start = visit.check_in_at or visit.created_at
    if start is None:
        return False
    return start <= now - timedelta(hours=24)


def id_held_inside_overdue_queryset(*, now=None):
    """INSIDE visits with retained ID past the 24h check-in boundary."""
    cutoff = (now or timezone.now()) - timedelta(hours=24)
    return (
        GuestVisit.objects.filter(status=VisitStatus.INSIDE, id_document_held=True)
        .filter(
            Q(check_in_at__lte=cutoff)
            | Q(check_in_at__isnull=True, created_at__lte=cutoff)
        )
        .select_related("guest", "company")
        .order_by("check_in_at", "id")
    )


ID_HELD_OVERDUE_EVENT_PREFIX = "visitor.id_held_overdue."


def id_held_overdue_event_key(visit_id: int, user_id: int, *, role_tag: str) -> str:
    return f"{ID_HELD_OVERDUE_EVENT_PREFIX}{visit_id}.{role_tag}.{user_id}"


def id_held_overdue_staff_recipients():
    """Active Reception + Security users (stable pk order). Display name only in alerts."""
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Role

    User = get_user_model()
    return User.objects.filter(
        is_active=True,
        role__in=(Role.RECEPTION, Role.SECURITY),
    ).order_by("pk")


def notify_id_held_inside_overdue(visit: GuestVisit) -> int:
    """One in-app alert per Reception/Security recipient × visit (idempotent).

    Distinct from cardless portal overdue and from RETURN_PENDING (known departure).
    Reading the alert does not close the visit or mark ID returned.
    """
    from apps.accounts.models import Role
    from apps.comms.models import Notification
    from apps.comms.services import notify_in_app

    if not is_id_held_inside_overdue(visit):
        return 0
    label = visit.guest.display_name if visit.guest_id else str(visit.pk)
    created = 0
    for user in id_held_overdue_staff_recipients():
        role_tag = "rec" if user.role == Role.RECEPTION else "sec"
        key = id_held_overdue_event_key(visit.pk, user.pk, role_tag=role_tag)
        existed = Notification.objects.filter(user=user, event_key=key).exists()
        if user.role == Role.RECEPTION:
            message = f"24 saat+ içəridə — vəsiqə hələ Reception-dadır: {label}"
        else:
            message = f"24 saat+ içəridə — vəsiqə saxlanılır (Security izləmə): {label}"
        note = notify_in_app(user=user, message=message, event_key=key)
        if note is not None and not existed:
            created += 1
    return created


def process_id_held_inside_overdue_alerts(*, now=None) -> dict:
    """Scheduler body: INSIDE + ID held past 24h → Reception/Security once each."""
    now = now or timezone.now()
    visits = list(id_held_inside_overdue_queryset(now=now))
    created = 0
    for visit in visits:
        created += notify_id_held_inside_overdue(visit)
    return {
        "visits": len(visits),
        "notifications_created": created,
        "as_of": now.isoformat(),
        "kind": "id_held_inside",
    }


def process_guest_overdue_alerts(*, now=None) -> dict:
    """Combined poller: cardless→portal + ID-held→Reception/Security. Safe to re-run.

    RETURN_PENDING (known departure, ID still held) is a separate event path —
    not labelled as inside overdue.
    """
    now = now or timezone.now()
    portal = process_portal_checkout_overdue_alerts(now=now)
    id_held = process_id_held_inside_overdue_alerts(now=now)
    return {
        "as_of": now.isoformat(),
        "portal_visits": portal["visits"],
        "portal_notifications_created": portal["notifications_created"],
        "id_held_visits": id_held["visits"],
        "id_held_notifications_created": id_held["notifications_created"],
        "visits": portal["visits"] + id_held["visits"],
        "notifications_created": (
            portal["notifications_created"] + id_held["notifications_created"]
        ),
    }


@transaction.atomic
def portal_check_out_visit(
    visit: GuestVisit, *, actor, company, departed_at=None
) -> GuestVisit:
    visit = GuestVisit.objects.select_for_update().select_related("company").get(pk=visit.pk)
    if company is None or visit.company_id != company.id:
        raise DomainError(_("Bu qonaq seçilmiş şirkətə aid deyil."))
    # Idempotent: already closed under portal-eligible rules stays closed.
    if visit.status == VisitStatus.LEFT:
        if visit.id_document_held or visit_has_active_guest_card(visit):
            raise DomainError(
                _("Bu qonağın çıxışını yalnız reception bağlaya bilər (vəsiqə və ya qonaq kartı).")
            )
        return visit
    if not can_portal_checkout(visit, company=company):
        raise DomainError(
            _("Bu qonağın çıxışını yalnız reception bağlaya bilər (vəsiqə və ya qonaq kartı).")
        )
    return ReceptionService.check_out_visit(
        visit,
        actor=actor,
        id_returned=True,
        departed_at=departed_at,
        checkout_source="portal",
    )


def _credentials_match(stored: str, incoming: str) -> bool:
    return bool(guest_card_match_keys(stored) & guest_card_match_keys(incoming))


def active_guest_credential_exists(card: str) -> bool:
    """True when an INSIDE visit has this guest card still ACTIVE (zero-safe match)."""
    if not normalize_guest_card(card):
        return False
    for access in VisitorAccess.objects.filter(
        status=VisitorAccessStatus.ACTIVE,
        visit__status=VisitStatus.INSIDE,
    ).only("credential"):
        if _credentials_match(access.credential, card):
            return True
    return False


GUEST_CHECKOUT_AMBIGUOUS_OP = "guest_checkout_ambiguous"
AXTRAX_SYNC_SYSTEM = "axtraxng"


def list_guest_access_matches(*, card: str, occurred_at) -> list[VisitorAccess]:
    """Return all VisitorAccess rows whose credential interval covers ``occurred_at``."""
    if not normalize_guest_card(card) or occurred_at is None:
        return []
    matches: list[VisitorAccess] = []
    qs = (
        VisitorAccess.objects.select_related("visit")
        .exclude(credential="")
        .filter(
            status__in=(
                VisitorAccessStatus.ACTIVE,
                VisitorAccessStatus.REVOKED,
                VisitorAccessStatus.EXPIRED,
            )
        )
        .order_by("visit_id")
    )
    for access in qs:
        if not _credentials_match(access.credential, card):
            continue
        start = access.valid_from or access.created_at
        end = access.valid_until
        if start and occurred_at < start:
            continue
        if end is not None and occurred_at > end:
            continue
        # Revoked without closed interval cannot claim historical ownership.
        if access.status == VisitorAccessStatus.REVOKED and end is None:
            continue
        matches.append(access)
    return matches


def find_guest_access_for_event(*, card: str, occurred_at) -> VisitorAccess | None:
    """Resolve historical card ownership for an OUT event.

    Uses assignment interval (``valid_from`` … ``valid_until``). Ambiguous matches
    (more than one row) return ``None`` so the open visit is preserved.
    """
    matches = list_guest_access_matches(card=card, occurred_at=occurred_at)
    if len(matches) != 1:
        return None
    return matches[0]


def _access_event_dedupe_key(event, *, card: str, occurred_at) -> str:
    """Prefer AccessEvent PK (maps to AxTrax IdAutoEvents via ExternalIdentity)."""
    pk = getattr(event, "pk", None)
    if pk:
        return f"access_event:{pk}"
    return f"card_time:{card}|{occurred_at.isoformat()}"


def _is_mapped_employee_event(event) -> bool:
    """True when AxTrax attribution resolved to a ResidentEmployee (not guest traffic)."""
    return bool(getattr(event, "employee_id", None) or getattr(event, "employee", None))


def record_ambiguous_guest_checkout(event, matches: list[VisitorAccess]) -> bool:
    """Write one SyncLog per AccessEvent for operator diagnosis. Returns True if created."""
    from apps.integrations.models import SyncLog, SyncStatus

    card = normalize_guest_card(getattr(event, "card_number", None) or "")
    occurred_at = getattr(event, "occurred_at", None)
    corr = _access_event_dedupe_key(event, card=card, occurred_at=occurred_at or timezone.now())
    if SyncLog.objects.filter(
        system=AXTRAX_SYNC_SYSTEM,
        operation=GUEST_CHECKOUT_AMBIGUOUS_OP,
        correlation_id=corr,
    ).exists():
        return False
    visit_ids = sorted({m.visit_id for m in matches if m.visit_id})
    access_ids = sorted({m.pk for m in matches if m.pk})
    SyncLog.objects.create(
        system=AXTRAX_SYNC_SYSTEM,
        operation=GUEST_CHECKOUT_AMBIGUOUS_OP,
        status=SyncStatus.ERROR,
        correlation_id=corr[:64],
        error_message="Ambiguous guest card match; visits left open",
        request_payload={
            "access_event_id": getattr(event, "pk", None),
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "card": card,
            "reader_id": getattr(event, "reader_id", None),
            "reader_name": (getattr(event, "reader_name", None) or "")[:80] or None,
        },
        response_payload={
            "reason": "ambiguous_guest_match",
            "match_count": len(matches),
            "visit_ids": visit_ids,
            "visitor_access_ids": access_ids,
        },
    )
    return True


def checkout_guests_from_access_events(events) -> int:
    """AxTrax OUT is passage evidence only for QONAQ guest-card custody.

    Reception owns physical card return and ID document custody. Matching OUT
    events are still recorded as AccessEvents by the sync layer; this hook must
    not set LEFT / RETURN_PENDING or mark physical items returned.

    Ambiguous multi-visit matches continue to write a SyncLog for diagnosis.
    Returns 0 guest checkouts finalized (always) for this City Point workflow.
    """
    from apps.residents.models import AccessEventType, AccessResult

    seen_event_keys: set[str] = set()
    for event in events or []:
        if getattr(event, "result", None) != AccessResult.GRANTED:
            continue
        if getattr(event, "event_type", None) != AccessEventType.OUT:
            continue
        if _is_mapped_employee_event(event):
            continue
        card = normalize_guest_card(getattr(event, "card_number", None) or "")
        occurred_at = getattr(event, "occurred_at", None)
        if not card or occurred_at is None:
            continue
        dedupe = _access_event_dedupe_key(event, card=card, occurred_at=occurred_at)
        if dedupe in seen_event_keys:
            continue
        seen_event_keys.add(dedupe)

        matches = list_guest_access_matches(card=card, occurred_at=occurred_at)
        if len(matches) > 1:
            record_ambiguous_guest_checkout(event, matches)
            continue
        # Single or zero match: leave visit status unchanged (Reception/portal close).
    return 0


def create_visitor_access(visit: GuestVisit, *, credential: str = "") -> VisitorAccess:
    card = normalize_guest_card(credential)
    now = timezone.now()
    start = visit.check_in_at or now
    access, _ = VisitorAccess.objects.get_or_create(
        visit=visit,
        defaults={
            "provider": "mock",
            "status": VisitorAccessStatus.PENDING,
            "sync_status": SyncStatus.PENDING,
            "valid_from": start,
            "valid_until": None,
            "credential": card,
        },
    )
    if card and access.credential != card:
        access.credential = card
    if not access.valid_from:
        access.valid_from = start
    try:
        from apps.integrations.adapters import MockAccessControlAdapter

        result = MockAccessControlAdapter().assign_credential(
            {
                "code": card or visit.invite_code or f"visit-{visit.pk}",
                "visit_id": visit.pk,
            }
        )
        access.external_id = result.external_id or access.external_id
        access.status = VisitorAccessStatus.ACTIVE if result.ok else VisitorAccessStatus.FAILED
        access.sync_status = SyncStatus.SUCCESS if result.ok else SyncStatus.ERROR
        access.last_error = result.error or ""
        access.last_sync_at = now
        access.save()
    except Exception as exc:
        access.status = VisitorAccessStatus.FAILED
        access.sync_status = SyncStatus.ERROR
        access.last_error = str(exc)
        access.last_sync_at = now
        access.save()
    return access


def revoke_visitor_access(visit: GuestVisit, *, until=None) -> None:
    """Revoke guest-card assignment; ``until`` closes the ownership interval (event time)."""
    access = getattr(visit, "visitor_access", None)
    if not access:
        return
    now = timezone.now()
    end = until or now
    try:
        from apps.integrations.adapters import MockAccessControlAdapter

        MockAccessControlAdapter().revoke_credential({"code": access.external_id or access.credential})
        access.status = VisitorAccessStatus.REVOKED
        access.sync_status = SyncStatus.SUCCESS
        access.last_sync_at = now
        access.last_error = ""
        if access.valid_until is None:
            access.valid_until = end
        access.save()
    except Exception as exc:
        access.sync_status = SyncStatus.ERROR
        access.last_error = str(exc)
        access.last_sync_at = now
        if access.valid_until is None:
            access.valid_until = end
        access.save()


def today_visits_queryset(day=None):
    day = day or timezone.localdate()
    return GuestVisit.objects.filter(scheduled_for=day).select_related(
        "guest", "company", "host", "visit_type", "visitor_access", "floor", "space"
    )


def visits_queryset_for_range(date_from, date_to):
    """Visits scheduled for an inclusive date range (export / reports)."""
    return GuestVisit.objects.filter(
        scheduled_for__gte=date_from,
        scheduled_for__lte=date_to,
    ).select_related("guest", "company", "host", "visit_type", "visitor_access", "floor", "space")


def inside_overdue_cutoff():
    return timezone.now() - timedelta(hours=24)


def id_pending_queryset():
    """Visits whose ID is still held or return is pending (matches the reception card)."""
    return (
        GuestVisit.objects.filter(
            Q(status=VisitStatus.RETURN_PENDING)
            | Q(id_document_held=True, status=VisitStatus.INSIDE)
        )
        .select_related("guest", "company", "host", "visit_type", "visitor_access", "floor", "space")
        .order_by("-updated_at", "-id")
    )


def inside_overdue_queryset():
    """Guests still INSIDE whose check-in (or create) was more than 24h ago."""
    cutoff = inside_overdue_cutoff()
    return (
        GuestVisit.objects.filter(status=VisitStatus.INSIDE)
        .filter(
            Q(check_in_at__lte=cutoff)
            | Q(check_in_at__isnull=True, created_at__lte=cutoff)
        )
        .select_related("guest", "company", "host", "visit_type", "visitor_access", "floor", "space")
        .order_by("check_in_at", "created_at")
    )


def filter_visits(qs, *, q="", status="", company_id=None, id_not_returned=False):
    if q:
        qn = q.strip()
        fin = normalize_fin(qn)
        name_fields = (
            "guest__first_name",
            "guest__last_name",
            "guest__full_name",
            "company__name",
            "host__full_name",
            "invite_code",
        )
        text_qs = filter_text_search(qs, qn, *name_fields)
        if fin:
            qs = qs.filter(
                Q(guest__fin_code__icontains=fin) | Q(pk__in=text_qs.values("pk"))
            )
        else:
            qs = text_qs
    if status == "inside":
        qs = qs.filter(status=VisitStatus.INSIDE)
    elif status == "inside_overdue":
        cutoff = inside_overdue_cutoff()
        qs = qs.filter(status=VisitStatus.INSIDE).filter(
            Q(check_in_at__lte=cutoff)
            | Q(check_in_at__isnull=True, created_at__lte=cutoff)
        )
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
