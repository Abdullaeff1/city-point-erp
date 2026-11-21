"""CRM domain services — leads, offers, lease applications, reminders."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import log_action
from apps.core.services import DomainError, Service
from apps.crm.access import (
    assert_can_approve_offer,
    assert_can_mutate_crm,
    assert_can_review_lease_application,
)
from apps.crm.models import (
    ActivityType,
    Lead,
    LeadActivity,
    LeadStatus,
    LeaseApplication,
    LeaseApplicationStatus,
    Offer,
    OfferStatus,
    OfferVersion,
    Opportunity,
    OpportunityStatus,
    Outcome,
    PipelineStage,
    Qualification,
    RecordStatus,
)


def default_rent_rate() -> Decimal:
    return Decimal(str(getattr(settings, "CRM_DEFAULT_RENT_RATE_PER_M2", "33.00")))


def default_vat_rate() -> Decimal:
    return Decimal(str(getattr(settings, "CRM_VAT_RATE", "18.00")))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_offer_totals(
    *,
    area_m2: Decimal | None,
    rent_rate_per_m2: Decimal,
    vat_rate: Decimal,
    discount_percent: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal, Decimal]:
    area = Decimal(area_m2 or 0)
    rate = Decimal(rent_rate_per_m2 or 0)
    disc = Decimal(discount_percent or 0)
    net = _money(area * rate * (Decimal("1") - disc / Decimal("100")))
    vat = _money(net * Decimal(vat_rate or 0) / Decimal("100"))
    return net, vat, _money(net + vat)


def find_duplicate_leads(
    *,
    phone: str = "",
    email: str = "",
    company_name: str = "",
    exclude_pk: int | None = None,
) -> list[Lead]:
    q = Q()
    phone = (phone or "").strip()
    email = (email or "").strip().lower()
    company = (company_name or "").strip()
    if phone:
        q |= Q(phone__iexact=phone)
    if email:
        q |= Q(email__iexact=email)
    if company and len(company) >= 3:
        q |= Q(company_name__icontains=company)
    if not q:
        return []
    qs = Lead.objects.filter(q)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return list(qs.order_by("-created_at")[:10])


class CrmLeadService(Service):
    @classmethod
    @transaction.atomic
    def create_lead(cls, *, actor, data: dict, notify: bool = True) -> Lead:
        assert_can_mutate_crm(actor)
        lead = Lead(
            full_name=(data.get("full_name") or "")[:200],
            email=(data.get("email") or "").strip(),
            phone=(data.get("phone") or "").strip()[:64],
            company_name=(data.get("company_name") or "")[:200],
            source=data.get("source") or "manual",
            source_note=(data.get("source_note") or "")[:255],
            inquired_at=data.get("inquired_at") or timezone.localdate(),
            min_area_m2=data.get("min_area_m2"),
            max_area_m2=data.get("max_area_m2"),
            employee_count=data.get("employee_count"),
            employee_count_raw=(data.get("employee_count_raw") or "")[:64],
            initial_note=data.get("initial_note") or "",
            message=data.get("message") or "",
            contact_missing_reason=data.get("contact_missing_reason") or "",
            interested_space=data.get("interested_space"),
            owner=data.get("owner") or actor,
            created_by=actor,
            qualification=data.get("qualification") or Qualification.UNREVIEWED,
            record_status=data.get("record_status") or RecordStatus.OPEN,
            pipeline_stage=data.get("pipeline_stage") or PipelineStage.WORKING,
            status=LeadStatus.NEW,
        )
        lead.full_clean()
        lead.save()
        LeadActivity.objects.create(
            lead=lead,
            activity_type=ActivityType.STATUS_CHANGE,
            body=_("Lid yaradıldı"),
            created_by=actor,
        )
        log_action(actor=actor, action="crm.lead.create", entity=lead, message=str(lead))
        if notify:
            notify_sales_new_lead(lead)
        return lead

    @classmethod
    @transaction.atomic
    def update_lead(cls, lead: Lead, *, actor, data: dict) -> Lead:
        assert_can_mutate_crm(actor)
        tracked = ("qualification", "pipeline_stage", "record_status", "outcome")
        before = {field: getattr(lead, field) for field in tracked}
        for field in (
            "full_name",
            "email",
            "phone",
            "company_name",
            "source",
            "source_note",
            "inquired_at",
            "min_area_m2",
            "max_area_m2",
            "employee_count",
            "employee_count_raw",
            "initial_note",
            "message",
            "contact_missing_reason",
            "qualification",
            "qualification_reason",
            "record_status",
            "pipeline_stage",
            "outcome",
            "outcome_note",
            "owner",
            "interested_space",
        ):
            if field in data:
                setattr(lead, field, data[field])
        if lead.qualification == Qualification.POTENTIAL and lead.status == LeadStatus.NEW:
            lead.status = LeadStatus.QUALIFIED
        if lead.qualification == Qualification.NON_POTENTIAL:
            lead.status = LeadStatus.DISQUALIFIED
            if lead.record_status != RecordStatus.CLOSED:
                lead.record_status = RecordStatus.CLOSED
        lead.full_clean()
        lead.save()
        changes = [
            f"{field}: {before[field]} → {getattr(lead, field)}"
            for field in tracked
            if field in data and before[field] != getattr(lead, field)
        ]
        if changes:
            LeadActivity.objects.create(
                lead=lead,
                activity_type=ActivityType.STATUS_CHANGE,
                body="; ".join(changes),
                created_by=actor,
            )
        log_action(actor=actor, action="crm.lead.update", entity=lead, message=str(lead))
        return lead

    @classmethod
    @transaction.atomic
    def add_activity(
        cls,
        lead: Lead,
        *,
        actor,
        activity_type: str = ActivityType.NOTE,
        body: str = "",
        occurred_at=None,
    ) -> LeadActivity:
        assert_can_mutate_crm(actor)
        act = LeadActivity.objects.create(
            lead=lead,
            activity_type=activity_type or ActivityType.NOTE,
            body=body or "",
            occurred_at=occurred_at or timezone.now(),
            created_by=actor,
        )
        log_action(actor=actor, action="crm.lead.activity", entity=lead, message=activity_type)
        return act


class CrmOpportunityService(Service):
    @classmethod
    @transaction.atomic
    def create_from_lead(cls, lead: Lead, *, actor, title: str = "", space=None) -> Opportunity:
        assert_can_mutate_crm(actor)
        if lead.qualification != Qualification.POTENTIAL:
            raise DomainError(_("Yalnız potensial lid üçün imkan yaradıla bilər."))
        opp = Opportunity.objects.create(
            lead=lead,
            title=(title or f"{lead.company_name or lead.full_name or 'Lead'} — İmkan")[:200],
            status=OpportunityStatus.OPEN,
            pipeline_stage=PipelineStage.WORKING,
            party=lead.party,
            expected_area=lead.max_area_m2 or lead.min_area_m2,
            employee_count=lead.employee_count,
            space=space or lead.interested_space,
            notes=lead.message or lead.initial_note or "",
            owner=lead.owner or actor,
            created_by=actor,
        )
        lead.status = LeadStatus.QUALIFIED
        lead.qualification = Qualification.POTENTIAL
        lead.save(update_fields=["status", "qualification", "updated_at"])
        LeadActivity.objects.create(
            lead=lead,
            activity_type=ActivityType.STATUS_CHANGE,
            body=_("İmkan yaradıldı (#%(id)s)") % {"id": opp.pk},
            created_by=actor,
        )
        log_action(actor=actor, action="crm.opportunity.create", entity=opp, message=opp.title)
        return opp

    @classmethod
    @transaction.atomic
    def set_stage(
        cls,
        opportunity: Opportunity,
        *,
        actor,
        stage: str,
        outcome: str = "",
        note: str = "",
        contact_channels: list | None = None,
    ) -> Opportunity:
        assert_can_mutate_crm(actor)
        opportunity.pipeline_stage = stage
        if stage == PipelineStage.WON:
            opportunity.status = OpportunityStatus.WON
            opportunity.outcome = outcome or Outcome.COOPERATION_SECURED
        elif stage == PipelineStage.LOST:
            opportunity.status = OpportunityStatus.LOST
            if not outcome:
                raise DomainError(_("İtirilmiş imkan üçün nəticə məcburidir."))
            if outcome == Outcome.OTHER and not (note or "").strip():
                raise DomainError(_("«Digər» itirmə səbəbi üçün izah məcburidir."))
            opportunity.outcome = outcome
        if note:
            opportunity.outcome_note = note
        if contact_channels is not None:
            opportunity.contact_channels = list(contact_channels)
        opportunity.save()
        if opportunity.lead_id:
            lead = opportunity.lead
            lead.pipeline_stage = stage
            if opportunity.outcome:
                lead.outcome = opportunity.outcome
                lead.outcome_note = opportunity.outcome_note
            if stage in (PipelineStage.WON, PipelineStage.LOST):
                lead.record_status = RecordStatus.CLOSED
            lead.save()
        LeadActivity.objects.create(
            lead=opportunity.lead,
            opportunity=opportunity,
            activity_type=ActivityType.STATUS_CHANGE,
            body=_("Mərhələ: %(stage)s") % {"stage": stage},
            created_by=actor,
        )
        log_action(actor=actor, action="crm.opportunity.stage", entity=opportunity, message=stage)
        return opportunity

    @classmethod
    @transaction.atomic
    def add_activity(
        cls,
        opportunity: Opportunity,
        *,
        actor,
        activity_type: str = ActivityType.NOTE,
        body: str = "",
        occurred_at=None,
    ) -> LeadActivity:
        assert_can_mutate_crm(actor)
        act = LeadActivity.objects.create(
            lead=opportunity.lead,
            opportunity=opportunity,
            activity_type=activity_type or ActivityType.NOTE,
            body=body or "",
            occurred_at=occurred_at or timezone.now(),
            created_by=actor,
        )
        log_action(
            actor=actor,
            action="crm.opportunity.activity",
            entity=opportunity,
            message=activity_type,
        )
        return act


class CrmOfferService(Service):
    WORKFLOW_CODE = "crm.offer.send"

    @classmethod
    @transaction.atomic
    def create_offer(
        cls,
        *,
        actor,
        opportunity: Opportunity,
        party=None,
        space=None,
        area_m2=None,
        rent_rate_per_m2=None,
        discount_percent=None,
        notes: str = "",
    ) -> Offer:
        assert_can_mutate_crm(actor)
        party = party or opportunity.party
        if party is None:
            raise DomainError(_("Təklif üçün party tələb olunur."))
        space = space or opportunity.space
        rate = Decimal(rent_rate_per_m2 if rent_rate_per_m2 is not None else default_rent_rate())
        vat = default_vat_rate()
        disc = Decimal(discount_percent or 0)
        area = Decimal(area_m2 if area_m2 is not None else (opportunity.expected_area or 0))
        net, vat_amt, gross = compute_offer_totals(
            area_m2=area, rent_rate_per_m2=rate, vat_rate=vat, discount_percent=disc
        )
        offer = Offer.objects.create(
            opportunity=opportunity,
            party=party,
            space=space,
            status=OfferStatus.DRAFT,
            rent_amount=net,
            notes=notes or "",
        )
        version = OfferVersion.objects.create(
            offer=offer,
            version_number=1,
            rent_rate_per_m2=rate,
            vat_rate=vat,
            area_m2=area or None,
            discount_percent=disc,
            monthly_rent_net=net,
            monthly_vat=vat_amt,
            monthly_rent_gross=gross,
            created_by=actor,
            notes=notes or "",
        )
        offer.current_version = version
        offer.save(update_fields=["current_version", "updated_at"])
        opportunity.pipeline_stage = PipelineStage.NEGOTIATION
        opportunity.save(update_fields=["pipeline_stage", "updated_at"])
        log_action(actor=actor, action="crm.offer.create", entity=offer, message=f"v{version.version_number}")
        return offer

    @classmethod
    @transaction.atomic
    def create_new_version(cls, offer: Offer, *, actor, data: dict) -> OfferVersion:
        assert_can_mutate_crm(actor)
        last = offer.versions.order_by("-version_number").first()
        n = (last.version_number if last else 0) + 1
        rate = Decimal(data.get("rent_rate_per_m2") if data.get("rent_rate_per_m2") is not None else default_rent_rate())
        vat = Decimal(data.get("vat_rate") if data.get("vat_rate") is not None else default_vat_rate())
        disc = Decimal(data.get("discount_percent") or 0)
        area = data.get("area_m2")
        if area is None and last:
            area = last.area_m2
        area = Decimal(area or 0)
        net, vat_amt, gross = compute_offer_totals(
            area_m2=area, rent_rate_per_m2=rate, vat_rate=vat, discount_percent=disc
        )
        version = OfferVersion.objects.create(
            offer=offer,
            version_number=n,
            rent_rate_per_m2=rate,
            vat_rate=vat,
            area_m2=area or None,
            discount_percent=disc,
            discount_note=(data.get("discount_note") or "")[:255],
            package_text=data.get("package_text") or (last.package_text if last else ""),
            monthly_rent_net=net,
            monthly_vat=vat_amt,
            monthly_rent_gross=gross,
            valid_until=data.get("valid_until"),
            notes=data.get("notes") or "",
            created_by=actor,
        )
        offer.current_version = version
        offer.status = OfferStatus.DRAFT
        offer.rent_amount = net
        offer.save(update_fields=["current_version", "status", "rent_amount", "updated_at"])
        log_action(actor=actor, action="crm.offer.version", entity=offer, message=f"v{n}")
        return version

    @classmethod
    @transaction.atomic
    def request_send_approval(cls, version: OfferVersion, *, actor) -> OfferVersion:
        assert_can_mutate_crm(actor)
        from apps.workflows.services import ApprovalService

        if version.is_locked and version.approval_request_id:
            raise DomainError(_("Bu versiya artıq təsdiqə göndərilib."))
        req = ApprovalService.request(
            workflow_code=cls.WORKFLOW_CODE,
            requested_by=actor,
            entity=version,
            payload={
                "offer_id": version.offer_id,
                "version_number": version.version_number,
                "monthly_rent_net": str(version.monthly_rent_net),
            },
        )
        version.approval_request = req
        version.is_locked = True
        version.save(update_fields=["approval_request", "is_locked"])
        offer = version.offer
        offer.status = OfferStatus.PENDING_APPROVAL
        offer.save(update_fields=["status", "updated_at"])
        log_action(actor=actor, action="crm.offer.approval_request", entity=offer, message=f"v{version.version_number}")
        return version

    @classmethod
    @transaction.atomic
    def decide_approval(cls, version: OfferVersion, *, actor, approved: bool, comment: str = "") -> OfferVersion:
        assert_can_approve_offer(actor)
        from apps.workflows.services import ApprovalService
        from apps.workflows.models import ApprovalStatus

        version = OfferVersion.objects.select_for_update().get(pk=version.pk)
        req = version.approval_request
        if not req or req.status != ApprovalStatus.PENDING:
            raise DomainError(_("Gözləyən təsdiq yoxdur."))
        ApprovalService.decide(req, approved=approved, decided_by=actor, comment=comment)
        offer = Offer.objects.select_for_update().get(pk=version.offer_id)
        if approved:
            offer.status = OfferStatus.APPROVED
        else:
            offer.status = OfferStatus.DRAFT
            version.is_locked = False
            version.save(update_fields=["is_locked"])
        offer.save(update_fields=["status", "updated_at"])
        log_action(
            actor=actor,
            action="crm.offer.approval_decide",
            entity=offer,
            message="approved" if approved else "rejected",
        )
        return version

    @classmethod
    @transaction.atomic
    def generate_pdf(cls, version: OfferVersion, *, actor=None, force: bool = False) -> OfferVersion:
        from apps.crm.pdf import ensure_offer_version_pdf

        version = OfferVersion.objects.select_for_update().get(pk=version.pk)
        ensure_offer_version_pdf(version, force=force)
        if actor:
            log_action(
                actor=actor,
                action="crm.offer.pdf",
                entity=version.offer,
                message=f"v{version.version_number}",
            )
        return version

    @classmethod
    @transaction.atomic
    def send_offer(cls, version: OfferVersion, *, actor, sent_to: str = "") -> Offer:
        assert_can_mutate_crm(actor)
        from django.conf import settings

        from apps.workflows.models import ApprovalStatus

        # Fresh rows — UI «Təsdiqlənib» versiya approval_request-ə görədir
        offer = Offer.objects.select_for_update().get(pk=version.offer_id)
        version = OfferVersion.objects.select_for_update().get(pk=version.pk)
        if offer.current_version_id != version.pk:
            raise DomainError(_("Yalnız cari versiya göndərilə bilər."))
        req = version.approval_request
        if not req or req.status != ApprovalStatus.APPROVED:
            raise DomainError(_("Təsdiqsiz təklif göndərilə bilməz. Əvvəl rəhbərlik təsdiqi lazımdır."))
        # PDF hazır olsun (göndərmə = status + PDF + email stub/log)
        cls.generate_pdf(version, actor=actor)
        version.refresh_from_db()
        # Versiya təsdiqlidirsə offer statusu geridə qalıbsa düzəlt (köhnə uyğunsuzluq)
        if offer.status not in (OfferStatus.APPROVED, OfferStatus.SENT):
            offer.status = OfferStatus.APPROVED
        offer.status = OfferStatus.SENT
        offer.sent_at = timezone.now()
        offer.sent_by = actor
        offer.sent_to = (sent_to or "")[:255]
        offer.save(update_fields=["status", "sent_at", "sent_by", "sent_to", "updated_at"])
        opp = offer.opportunity
        opp.pipeline_stage = PipelineStage.OFFER_SENT
        opp.save(update_fields=["pipeline_stage", "updated_at"])
        if opp.lead_id:
            opp.lead.pipeline_stage = PipelineStage.OFFER_SENT
            opp.lead.save(update_fields=["pipeline_stage", "updated_at"])
        # Email via NotificationDispatch after commit (default off: CRM_OFFER_SEND_EMAIL=0).
        # Failures are recorded on the dispatch row — SENT status is not rolled back.
        if getattr(settings, "CRM_OFFER_SEND_EMAIL", False) and offer.sent_to:
            from apps.comms.mail import send_templated_email

            recipient = offer.sent_to
            subject = f"City Point təklif #{offer.pk}"
            body = _("Təklif PDF əlavə olunub (v%(v)s).") % {"v": version.version_number}
            payload = {
                "offer_id": offer.pk,
                "version_number": version.version_number,
            }
            attachments = []
            if version.pdf_file:
                try:
                    version.pdf_file.open("rb")
                    pdf_bytes = version.pdf_file.read()
                    version.pdf_file.close()
                    attachments.append(
                        (
                            f"offer_{offer.pk}_v{version.version_number}.pdf",
                            pdf_bytes,
                            "application/pdf",
                        )
                    )
                except Exception:  # noqa: BLE001
                    attachments = []

            def _send():
                try:
                    send_templated_email(
                        recipient=recipient,
                        subject=subject,
                        body=body,
                        template_code="crm.offer.sent",
                        payload=payload,
                        attachments=attachments or None,
                    )
                except Exception:  # noqa: BLE001 — dispatch row already marked failed
                    pass

            transaction.on_commit(_send)
        log_action(
            actor=actor,
            action="crm.offer.send",
            entity=offer,
            message=f"v{version.version_number} → {offer.sent_to}",
        )
        return offer


def compose_bank_details(requisites: dict | None) -> str:
    """Word forma bank alt sahələrindən oxunaqlı mətn."""
    req = requisites or {}
    labels = (
        ("currency", "Valyuta"),
        ("bank_name", "Bankın adı"),
        ("branch_code", "Filialın kodu"),
        ("voen", "VÖEN"),
        ("swift", "SWIFT"),
        ("current_account", "M.H."),
        ("correspondent", "H.H."),
    )
    lines = []
    for key, label in labels:
        val = (req.get(key) or "").strip()
        if val:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


class LeaseApplicationService(Service):
    @classmethod
    def _snapshot(cls, app: LeaseApplication) -> dict:
        return {
            "person_name": app.person_name,
            "tax_id": app.tax_id,
            "legal_address": app.legal_address,
            "actual_address": app.actual_address,
            "floor_label": app.floor_label,
            "space_label": app.space_label,
            "use_purpose": app.use_purpose,
            "rent_rate_per_m2": str(app.rent_rate_per_m2) if app.rent_rate_per_m2 is not None else "",
            "monthly_rent_net": str(app.monthly_rent_net) if app.monthly_rent_net is not None else "",
            "deposit_amount": str(app.deposit_amount) if app.deposit_amount is not None else "",
            "rent_free_note": app.rent_free_note,
            "cleaning_included": app.cleaning_included,
            "tea_service_included": app.tea_service_included,
            "lease_start": app.lease_start.isoformat() if app.lease_start else "",
            "lease_end": app.lease_end.isoformat() if app.lease_end else "",
            "application_date": app.application_date.isoformat() if app.application_date else "",
            "bank_details": app.bank_details,
            "bank_requisites": app.bank_requisites or {},
            "fit_out_notes": app.fit_out_notes,
            "extra_notes": app.extra_notes,
            "signer_title_name": app.signer_title_name,
            "is_legal_entity": app.is_legal_entity,
            "attachment_checklist": app.attachment_checklist or {},
        }

    @classmethod
    def _apply_bank_requisites(cls, app: LeaseApplication, requisites: dict | None) -> None:
        if requisites is None:
            return
        cleaned = {
            k: (str(requisites.get(k) or "").strip())[:255]
            for k in (
                "currency",
                "bank_name",
                "branch_code",
                "voen",
                "swift",
                "current_account",
                "correspondent",
            )
        }
        app.bank_requisites = cleaned
        composed = compose_bank_details(cleaned)
        if composed:
            app.bank_details = composed

    @classmethod
    def _open_application_for_offer(cls, offer: Offer) -> LeaseApplication | None:
        return (
            LeaseApplication.objects.filter(offer_id=offer.pk)
            .exclude(status=LeaseApplicationStatus.CANCELLED)
            .order_by("pk")
            .first()
        )

    @classmethod
    @transaction.atomic
    def create_from_offer(cls, offer: Offer, *, actor, data: dict | None = None) -> LeaseApplication:
        assert_can_mutate_crm(actor)
        offer = Offer.objects.select_for_update().get(pk=offer.pk)
        if offer.status not in (OfferStatus.SENT, OfferStatus.ACCEPTED, OfferStatus.APPROVED):
            raise DomainError(_("Müraciət formu üçün təklif göndərilmiş/qəbul olunmuş olmalıdır."))

        existing = cls._open_application_for_offer(offer)
        if existing:
            return existing

        ver = offer.current_version
        data = data or {}
        party_name = ""
        if offer.party_id:
            party_name = getattr(offer.party, "legal_name", None) or str(offer.party)
        floor_label = (data.get("floor_label") or "")[:64]
        if not floor_label and offer.space_id and getattr(offer.space, "floor_id", None):
            floor = offer.space.floor
            floor_label = (getattr(floor, "code", None) or getattr(floor, "name", "") or "")[:64]
        app = LeaseApplication(
            offer=offer,
            offer_version=ver,
            opportunity=offer.opportunity,
            space=offer.space,
            lease_id=offer.lease_id,
            person_name=data.get("person_name") or (party_name or "")[:200],
            tax_id=(data.get("tax_id") or "")[:32],
            rent_rate_per_m2=data.get("rent_rate_per_m2") or (ver.rent_rate_per_m2 if ver else None),
            monthly_rent_net=data.get("monthly_rent_net") or (ver.monthly_rent_net if ver else None),
            space_label=(data.get("space_label") or (str(offer.space) if offer.space_id else ""))[:128],
            floor_label=floor_label,
            application_date=data.get("application_date") or timezone.localdate(),
            created_by=actor,
            status=LeaseApplicationStatus.DRAFT,
        )
        for field in (
            "legal_address",
            "actual_address",
            "use_purpose",
            "deposit_amount",
            "rent_free_note",
            "cleaning_included",
            "tea_service_included",
            "lease_start",
            "lease_end",
            "bank_details",
            "fit_out_notes",
            "extra_notes",
            "signer_title_name",
            "is_legal_entity",
            "attachment_checklist",
            "sales_notes",
            "application_date",
        ):
            if field in data and data[field] is not None:
                setattr(app, field, data[field])
        if "bank_requisites" in data:
            cls._apply_bank_requisites(app, data.get("bank_requisites") or {})
        app.form_snapshot = cls._snapshot(app)
        app.save()
        if offer.opportunity_id:
            offer.opportunity.pipeline_stage = PipelineStage.LEASE_STAGE
            offer.opportunity.save(update_fields=["pipeline_stage", "updated_at"])
        log_action(actor=actor, action="crm.lease_app.create", entity=app, message=str(app.pk))
        return app

    @classmethod
    @transaction.atomic
    def update_draft(cls, app: LeaseApplication, *, actor, data: dict) -> LeaseApplication:
        assert_can_mutate_crm(actor)
        if app.status not in (
            LeaseApplicationStatus.DRAFT,
            LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
        ):
            raise DomainError(_("Yalnız qaralama / düzəliş statusunda redaktə olunur."))
        requisites = data.get("bank_requisites") if "bank_requisites" in data else None
        for field, value in data.items():
            if field == "bank_requisites":
                continue
            if hasattr(app, field) and field not in ("status", "lease", "id"):
                setattr(app, field, value)
        if requisites is not None:
            cls._apply_bank_requisites(app, requisites)
        app.form_snapshot = cls._snapshot(app)
        app.save()
        return app

    @classmethod
    def assert_attachment_checklist(cls, app: LeaseApplication) -> None:
        """Enforce Word-form attachment intent before accounting submit (checklist, not files)."""
        chk = app.attachment_checklist if isinstance(app.attachment_checklist, dict) else {}
        required = ["voen", "bank"]
        if app.is_legal_entity:
            required.append("registry")
        missing = [k for k in required if not chk.get(k)]
        if missing:
            labels = {"voen": "VÖEN", "bank": "Bank rekvizitləri", "registry": "Reyestrdən çıxarış"}
            raise DomainError(
                _("Əlavə checklist tamamlanmayıb: %(docs)s.")
                % {"docs": ", ".join(labels.get(m, m) for m in missing)}
            )

    @classmethod
    @transaction.atomic
    def submit_to_accounting(cls, app: LeaseApplication, *, actor) -> LeaseApplication:
        assert_can_mutate_crm(actor)
        if app.status not in (
            LeaseApplicationStatus.DRAFT,
            LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
        ):
            raise DomainError(_("Müraciət göndərilə bilməz."))
        cls.assert_attachment_checklist(app)
        app.form_snapshot = cls._snapshot(app)
        app.status = LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING
        app.submitted_by = actor
        app.submitted_at = timezone.now()
        app.save()
        log_action(actor=actor, action="crm.lease_app.submit", entity=app, message=str(app.pk))
        from apps.accounts.models import Role
        from apps.comms.services import notify_in_app
        from django.contrib.auth import get_user_model

        User = get_user_model()
        label = getattr(app, "code", None) or str(app.pk)
        for user in User.objects.filter(role=Role.ACCOUNTANT, is_active=True)[:20]:
            notify_in_app(
                user=user,
                message=f"İcarə müraciəti mühasibatlığa göndərildi: {label}",
                event_key=f"crm.lease_app.submit.{app.pk}.{user.pk}",
            )
        return app

    @classmethod
    @transaction.atomic
    def accountant_accept(cls, app: LeaseApplication, *, actor, notes: str = "") -> LeaseApplication:
        assert_can_review_lease_application(actor)
        if app.status not in (
            LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING,
            LeaseApplicationStatus.UNDER_REVIEW,
        ):
            raise DomainError(_("Bu statusda qəbul edilə bilməz."))
        app.status = LeaseApplicationStatus.UNDER_REVIEW
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        if notes:
            app.accountant_notes = notes
        app.save()
        return app

    @classmethod
    @transaction.atomic
    def accountant_return(cls, app: LeaseApplication, *, actor, notes: str = "") -> LeaseApplication:
        assert_can_review_lease_application(actor)
        app.status = LeaseApplicationStatus.RETURNED_FOR_CORRECTION
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        app.accountant_notes = notes or app.accountant_notes
        app.save()
        log_action(actor=actor, action="crm.lease_app.return", entity=app, message=notes[:200])
        return app

    @classmethod
    def _compose_lease_notes_from_app(cls, app: LeaseApplication, base: str = "") -> str:
        parts = []
        if (base or "").strip():
            parts.append(base.strip())
        if app.use_purpose:
            parts.append(f"Təyinat: {app.use_purpose.strip()[:200]}")
        if app.rent_free_note:
            parts.append(f"Azadolma: {app.rent_free_note.strip()[:255]}")
        if app.cleaning_included is True:
            parts.append("Təmizlik: icarəyə daxil")
        elif app.cleaning_included is False:
            parts.append("Təmizlik: ayrıca ödənişli")
        if app.tea_service_included is True:
            parts.append("Çay xidməti: icarəyə daxil")
        elif app.tea_service_included is False:
            parts.append("Çay xidməti: ayrıca ödənişli")
        bank_bits = []
        if app.tax_id:
            bank_bits.append(f"VÖEN: {app.tax_id}")
        if app.bank_details:
            bank_bits.append(f"Bank: {app.bank_details.strip()[:500]}")
        req = app.bank_requisites if isinstance(app.bank_requisites, dict) else {}
        for key in ("currency", "bank_name", "branch_code", "voen", "swift", "current_account", "correspondent"):
            if req.get(key):
                bank_bits.append(f"{key}: {req[key]}")
        if bank_bits:
            parts.append(f"[LeaseApplication #{app.pk}] " + " | ".join(bank_bits))
        return "\n".join(parts)

    @classmethod
    def _ensure_separate_service_addons(cls, lease, app: LeaseApplication) -> None:
        """When cleaning/tea are NOT included, create inactive Addon stubs (rate must be set later)."""
        from apps.leases.models import LeaseAddon

        specs = []
        if app.cleaning_included is False:
            specs.append(("cleaning", "Təmizlik xidməti"))
        if app.tea_service_included is False:
            specs.append(("tea", "Çay xidməti"))
        for code, label in specs:
            LeaseAddon.objects.get_or_create(
                lease=lease,
                code=code,
                defaults={"label": label, "rate_per_m2": Decimal("0"), "is_active": False},
            )

    @classmethod
    @transaction.atomic
    def create_lease_draft(cls, app: LeaseApplication, *, actor) -> LeaseApplication:
        assert_can_review_lease_application(actor)
        from apps.core import events as bus
        from apps.leases.lease_ops import refresh_lease_cached_amounts
        from apps.leases.models import Lease, LeaseStatus
        from apps.leases.services import (
            ensure_primary_lease_line,
            lock_space_for_reservation,
            next_lease_code,
            space_commercially_held,
            sync_space_from_lease,
        )

        app = LeaseApplication.objects.select_for_update().get(pk=app.pk)
        if app.status == LeaseApplicationStatus.CANCELLED:
            raise DomainError(_("Ləğv olunmuş müraciət üçün icarə yaradıla bilməz."))

        # Idempotent: app already linked
        if app.lease_id:
            return app

        offer = Offer.objects.select_for_update().get(pk=app.offer_id) if app.offer_id else None

        # Reuse offer.lease if another path already bound
        if offer is not None and offer.lease_id:
            app.lease_id = offer.lease_id
            app.status = LeaseApplicationStatus.LEASE_DRAFT_CREATED
            app.reviewed_by = actor
            app.reviewed_at = timezone.now()
            app.save(
                update_fields=["lease", "status", "reviewed_by", "reviewed_at", "updated_at"]
            )
            return app

        party = offer.party if offer is not None else None
        if party is None:
            raise DomainError(_("Party yoxdur — lease yaradıla bilməz."))

        space_id = app.space_id or (offer.space_id if offer is not None else None)
        if space_id:
            lock_space_for_reservation(space_id)
            if space_commercially_held(space_id):
                raise DomainError(
                    _("Bu sahə artıq kommersiya rezervindədir — təkrar rezerv mümkün deyil.")
                )

        rate = app.rent_rate_per_m2 or default_rent_rate()
        rent = app.monthly_rent_net or 0
        deposit = app.deposit_amount if app.deposit_amount is not None else Decimal("0")
        notes = cls._compose_lease_notes_from_app(app, base=app.extra_notes or app.sales_notes or "")
        lease = Lease.objects.create(
            code=next_lease_code(),
            party=party,
            space_id=space_id,
            status=LeaseStatus.NEGOTIATION,
            rent=rent,
            rent_rate_per_m2=rate,
            service_rate_per_m2=Decimal("0"),
            deposit=deposit if deposit and deposit > 0 else Decimal("0"),
            deposit_months=2,
            parking_included_free=True,
            start_date=app.lease_start,
            end_date=app.lease_end,
            fit_out_notes=(app.fit_out_notes or "")[:255],
            notes=notes,
        )
        ensure_primary_lease_line(lease)
        refresh_lease_cached_amounts(lease)
        cls._ensure_separate_service_addons(lease, app)
        sync_space_from_lease(lease)

        app.lease = lease
        app.status = LeaseApplicationStatus.LEASE_DRAFT_CREATED
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        app.save()
        if offer is not None:
            offer.lease = lease
            offer.status = OfferStatus.ACCEPTED
            offer.save(update_fields=["lease", "status", "updated_at"])
            opp = offer.opportunity
            if opp:
                # Do not mark WON until signed/complete — keep lease_stage while open.
                opp.pipeline_stage = PipelineStage.LEASE_STAGE
                opp.save(update_fields=["pipeline_stage", "updated_at"])
        bus.emit(
            bus.LEASE_DRAFT_CREATED,
            payload={
                "lease_id": lease.pk,
                "application_id": app.pk,
                "space_id": space_id,
                "code": lease.code,
                "entity_model": "lease",
            },
            actor=actor,
            event_key=f"lease.draft.{lease.pk}",
        )
        log_action(actor=actor, action="crm.lease_app.lease_draft", entity=app, message=lease.code)
        return app

    @classmethod
    @transaction.atomic
    def reject_offer(cls, offer: Offer, *, actor, reason: str = "") -> Offer:
        """Client/commercial reject — release pre-active hold if this offer owns the lease."""
        assert_can_mutate_crm(actor)
        offer = Offer.objects.select_for_update().get(pk=offer.pk)
        if offer.status == OfferStatus.REJECTED:
            return offer
        if offer.status == OfferStatus.ACCEPTED and offer.lease_id:
            from apps.leases.models import LeaseStatus
            from apps.leases.services import terminate_lease

            lease = offer.lease
            if lease and lease.status in (
                LeaseStatus.DRAFT,
                LeaseStatus.NEGOTIATION,
                LeaseStatus.APPROVED,
                LeaseStatus.SIGNED,
            ):
                terminate_lease(lease, actor=actor)
        offer.status = OfferStatus.REJECTED
        if reason:
            offer.notes = ((offer.notes or "") + f"\nReject: {reason}").strip()[:5000]
            offer.save(update_fields=["status", "notes", "updated_at"])
        else:
            offer.save(update_fields=["status", "updated_at"])
        opp = offer.opportunity
        if opp and opp.status == OpportunityStatus.OPEN:
            opp.status = OpportunityStatus.LOST
            opp.pipeline_stage = PipelineStage.LOST
            opp.outcome = Outcome.OFFER_REJECTED
            if reason:
                opp.outcome_note = reason[:2000]
            opp.save()
        for app in LeaseApplication.objects.filter(offer=offer).exclude(
            status__in=(LeaseApplicationStatus.COMPLETED, LeaseApplicationStatus.CANCELLED)
        ):
            app.status = LeaseApplicationStatus.CANCELLED
            app.save(update_fields=["status", "updated_at"])
        log_action(actor=actor, action="crm.offer.reject", entity=offer, message=reason[:200])
        # Customer/commercial reject (not Management approval.decide) → opportunity owner.
        owner = getattr(opp, "owner", None) if opp else None
        if owner is None or not owner.is_active:
            owner = getattr(opp, "created_by", None) if opp else None
        if owner is not None and owner.is_active:
            from apps.comms.services import notify_in_app

            notify_in_app(
                user=owner,
                message=f"Ticarət təklifi rədd edildi (#{offer.pk})",
                event_key=f"crm.offer.rejected.{offer.pk}",
            )
        return offer

    @classmethod
    @transaction.atomic
    def create_fit_out_work_order(cls, app: LeaseApplication, *, actor, pay_note: str = "") -> object:
        """Authorized handoff: LeaseApplication fit-out notes → Facility WorkOrder (idempotent)."""
        from apps.core import events as bus
        from apps.maintenance.models import WorkOrder, WorkOrderStatus
        from apps.maintenance.services import next_wo_code

        assert_can_review_lease_application(actor)
        notes = (app.fit_out_notes or "").strip()
        if not notes:
            raise DomainError(_("Təmir / fit-out qeydi yoxdur — iş əmri yaradıla bilməz."))
        if not app.lease_id:
            raise DomainError(_("Əvvəlcə icarə qaralaması yaradılmalıdır."))

        marker = f"[lease-fitout:{app.lease.code}]"
        existing = (
            WorkOrder.objects.filter(description__contains=marker)
            .exclude(status=WorkOrderStatus.COMPLETED)
            .first()
        )
        if existing:
            return existing

        desc = f"{marker}\n{notes}"
        if pay_note:
            desc += f"\nÖdəniş məsuliyyəti: {pay_note.strip()[:500]}"
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title=f"Fit-out · {app.lease.code}"[:200],
            description=desc,
            status=WorkOrderStatus.OPEN,
            space=app.space or app.lease.space,
            party=app.lease.party,
            billable=False,
        )
        bus.emit(
            bus.WORK_ORDER_CREATED,
            payload={"work_order_id": wo.pk, "code": wo.code, "lease_id": app.lease_id},
            actor=actor,
            event_key=f"wo.created.{wo.pk}",
        )
        log_action(actor=actor, action="crm.lease_app.fitout_wo", entity=app, message=wo.code)
        return wo

    @classmethod
    @transaction.atomic
    def cancel_lease_application(cls, app: LeaseApplication, *, actor, reason: str = "") -> LeaseApplication:
        assert_can_mutate_crm(actor)
        app = LeaseApplication.objects.select_for_update().get(pk=app.pk)
        if app.status == LeaseApplicationStatus.CANCELLED:
            return app
        if app.status == LeaseApplicationStatus.COMPLETED:
            raise DomainError(_("Tamamlanmış müraciət ləğv edilə bilməz."))
        if app.lease_id:
            from apps.leases.models import LeaseStatus
            from apps.leases.services import terminate_lease

            lease = app.lease
            if lease and lease.status in (
                LeaseStatus.DRAFT,
                LeaseStatus.NEGOTIATION,
                LeaseStatus.APPROVED,
                LeaseStatus.SIGNED,
            ):
                terminate_lease(lease, actor=actor)
        app.status = LeaseApplicationStatus.CANCELLED
        if reason:
            app.sales_notes = ((app.sales_notes or "") + f"\nCancel: {reason}").strip()
        app.save()
        log_action(actor=actor, action="crm.lease_app.cancel", entity=app, message=reason[:200])
        return app

    @classmethod
    def ensure_document_type_lease_application_signed(cls):
        from apps.documents.models import (
            DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
            DEFAULT_RETENTION_DAYS,
            DocumentSensitivity,
            DocumentType,
        )

        obj, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
            defaults={
                "name": "İmzalanmış müraciət forması",
                "retention_days": DEFAULT_RETENTION_DAYS.get(
                    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, 3650
                ),
                "default_sensitivity": DocumentSensitivity.CONFIDENTIAL,
            },
        )
        return obj

    @classmethod
    def resolve_application_company(cls, app: LeaseApplication, *, create: bool = False):
        """Find or optionally create ResidentCompany for application (copy-if-empty later)."""
        from django.utils.text import slugify

        from apps.residents.models import ResidentCompany

        company = None
        if app.tax_id:
            company = ResidentCompany.objects.filter(voen=app.tax_id).first()
        if company is None and app.person_name:
            company = ResidentCompany.objects.filter(name__iexact=app.person_name.strip()).first()
        if company is None and app.offer_id and app.offer.party_id:
            cid = getattr(app.offer.party, "legacy_resident_company_id", None)
            if cid:
                company = ResidentCompany.objects.filter(pk=cid).first()
        if company is None and create and (app.person_name or app.tax_id):
            base = slugify(app.person_name or app.tax_id or "company")[:40] or "company"
            slug = base
            n = 1
            while ResidentCompany.objects.filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            from apps.residents.models import CompanyStatus

            company = ResidentCompany.objects.create(
                name=(app.person_name or app.tax_id or slug)[:160],
                slug=slug,
                voen=(app.tax_id or "")[:32],
                legal_address=(app.legal_address or "")[:255],
                actual_address=(app.actual_address or "")[:255],
                status=CompanyStatus.ACTIVE,
                portal_active=False,
            )
        return company

    @classmethod
    def application_has_signed_document(cls, app: LeaseApplication) -> bool:
        """True when a real uploaded signed application PDF/scan exists for the company/lease."""
        from apps.documents.models import DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, Document

        cls.ensure_document_type_lease_application_signed()
        company = cls.resolve_application_company(app, create=False)
        qs = Document.objects.filter(
            document_type__code=DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED
        ).exclude(file="")
        if app.lease_id and qs.filter(lease_id=app.lease_id).exists():
            return True
        if company and qs.filter(company_id=company.pk).exists():
            return True
        return False

    @classmethod
    def assert_supporting_documents(cls, app: LeaseApplication) -> None:
        """Require actual Document rows for VOEN/bank/(registry for legal entity)."""
        from apps.documents.models import (
            DOCUMENT_TYPE_BANK_CERTIFICATE,
            DOCUMENT_TYPE_COMPANY_EXTRACT,
            DOCUMENT_TYPE_VOEN,
            Document,
        )
        from apps.residents.models import ResidentCompany

        company = None
        if app.tax_id:
            company = ResidentCompany.objects.filter(voen=app.tax_id).first()
        if company is None and app.offer_id and getattr(app.offer, "party", None):
            company_id = getattr(app.offer.party, "legacy_resident_company_id", None)
            if company_id:
                company = ResidentCompany.objects.filter(pk=company_id).first()
        if company is None:
            # Soft: cannot validate files without company card yet — checklist alone insufficient
            # for complete; allow draft/submit with warning only at complete stage.
            return

        def _has(code: str) -> bool:
            return Document.objects.filter(
                company=company, document_type__code=code
            ).exclude(file="").exists()

        missing = []
        if not _has(DOCUMENT_TYPE_VOEN):
            missing.append(_("VÖEN sənədi"))
        if not _has(DOCUMENT_TYPE_BANK_CERTIFICATE):
            missing.append(_("Bank rekvizitləri sənədi"))
        if app.is_legal_entity and not _has(DOCUMENT_TYPE_COMPANY_EXTRACT):
            missing.append(_("Reyestrdən çıxarış"))
        if missing:
            raise DomainError(
                _("Tələb olunan sənədlər yoxdur: %(docs)s. Rezident kartından yükləyin.")
                % {"docs": ", ".join(str(m) for m in missing)}
            )

    @classmethod
    @transaction.atomic
    def mark_signed_and_complete(cls, app: LeaseApplication, *, actor, upsert_party: bool = True) -> LeaseApplication:
        """İmza: Signed/Upcoming → start_date-də Active; resident+portal; opportunity Won."""
        assert_can_review_lease_application(actor)
        from apps.leases.models import LeaseStatus
        from apps.leases.services import activate_lease, sync_space_from_lease
        from apps.parties.models import PartyRole, PartyRoleCode, PartyStatus
        from apps.parties.resolvers import party_for_company
        from apps.residents.models import ResidentCompany

        app = LeaseApplication.objects.select_for_update().get(pk=app.pk)
        if app.status == LeaseApplicationStatus.COMPLETED:
            return app
        if app.status == LeaseApplicationStatus.CANCELLED:
            raise DomainError(_("Ləğv olunmuş müraciət tamamlanmaz."))
        if not app.lease_id:
            raise DomainError(_("Əvvəlcə icarə qaralaması yaradılmalıdır."))

        company = None
        if upsert_party:
            company = cls.resolve_application_company(app, create=True)
            if company is not None:
                updates = []
                if app.legal_address and not company.legal_address:
                    company.legal_address = app.legal_address[:255]
                    updates.append("legal_address")
                if app.actual_address and not company.actual_address:
                    company.actual_address = app.actual_address[:255]
                    updates.append("actual_address")
                if app.tax_id and not company.voen:
                    company.voen = app.tax_id[:32]
                    updates.append("voen")
                req = app.bank_requisites if isinstance(app.bank_requisites, dict) else {}
                if req.get("bank_name") and not company.bank_name:
                    company.bank_name = str(req["bank_name"])[:160]
                    updates.append("bank_name")
                if req.get("voen") and not company.bank_voen:
                    company.bank_voen = str(req["voen"])[:32]
                    updates.append("bank_voen")
                if updates:
                    company.save(update_fields=updates)

        cls.assert_supporting_documents(app)
        if not cls.application_has_signed_document(app):
            raise DomainError(
                _(
                    "İmzalanmış müraciət forması (PDF/scan) yüklənməlidir. "
                    "Rezident sənədlərinə «İmzalanmış müraciət forması» əlavə edin."
                )
            )

        app.status = LeaseApplicationStatus.SIGNED_DOCUMENTS_RECEIVED
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        app.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

        party = None
        if app.offer_id and app.offer.party_id:
            party = app.offer.party
        if company is not None:
            party = party_for_company(company, ensure=True) or party

        lease = app.lease
        if lease:
            today = timezone.localdate()
            start = lease.start_date or app.lease_start or today
            if not lease.start_date:
                lease.start_date = start
            # İmza → Signed; start_date ≤ bugün → Active (+ billing)
            if start <= today:
                activate_lease(lease, actor=actor)
            else:
                lease.status = LeaseStatus.SIGNED
                lease.billing_active = False
                lease.portal_eligible = False
                lease.access_eligible = False
                lease.save(
                    update_fields=[
                        "status",
                        "start_date",
                        "billing_active",
                        "portal_eligible",
                        "access_eligible",
                        "updated_at",
                    ]
                )
                sync_space_from_lease(lease)
            party = party or lease.party

        # Resident aktivləşmə yalnız imzada; prospect erkən qala bilər
        if party:
            if party.status != PartyStatus.ACTIVE and (
                lease and lease.status == LeaseStatus.ACTIVE
            ):
                party.status = PartyStatus.ACTIVE
                party.save(update_fields=["status", "updated_at"])
            PartyRole.objects.get_or_create(
                party=party,
                role=PartyRoleCode.RESIDENT,
                defaults={"is_primary": True},
            )

        app.status = LeaseApplicationStatus.COMPLETED
        app.save(update_fields=["status", "updated_at"])
        if app.opportunity_id:
            opp = app.opportunity
            opp.status = OpportunityStatus.WON
            opp.pipeline_stage = PipelineStage.WON
            opp.outcome = Outcome.COOPERATION_SECURED
            opp.save()
            if opp.lead_id:
                lead = opp.lead
                lead.pipeline_stage = PipelineStage.WON
                lead.record_status = RecordStatus.CLOSED
                lead.outcome = Outcome.COOPERATION_SECURED
                lead.status = LeadStatus.CONVERTED
                lead.save()
        log_action(actor=actor, action="crm.lease_app.complete", entity=app, message=str(app.pk))
        return app


# --- Reminder / notify -------------------------------------------------------


def sales_users() -> Iterable:
    from apps.accounts.models import Role, User

    return User.objects.filter(role=Role.SALES, is_active=True)


def notify_sales_new_lead(lead: Lead) -> None:
    from apps.comms.services import notify_in_app

    msg = _("Yeni lid: %(name)s") % {"name": str(lead)}
    for user in sales_users():
        notify_in_app(user=user, message=msg[:255], event_key=f"crm.lead.new.{lead.pk}")


def scan_lead_activity_reminders(*, limit: int = 200) -> dict[str, int]:
    """24 iş saatı lid aktivliksiz → sales reminder (idempotent)."""
    from apps.comms.models import Notification
    from apps.comms.services import notify_in_app
    from apps.tickets.business_calendar import add_business_hours

    stats = {"checked": 0, "reminded": 0}
    now = timezone.now()
    qs = (
        Lead.objects.filter(record_status=RecordStatus.OPEN)
        .exclude(qualification=Qualification.NON_POTENTIAL)
        .order_by("created_at")[:limit]
    )
    for lead in qs:
        stats["checked"] += 1
        created = lead.created_at
        due = add_business_hours(created, 24)
        if now < due:
            continue
        if lead.activities.exclude(activity_type=ActivityType.STATUS_CHANGE).exists():
            continue
        day_key = timezone.localdate(created).isoformat()
        ek = f"crm.lead.idle24bh.{lead.pk}.{day_key}"
        if Notification.objects.filter(event_key=ek).exists():
            continue
        msg = _("Lid 24 iş saatı aktivliksiz: %(name)s") % {"name": str(lead)}
        targets = list(sales_users())
        if lead.owner_id and lead.owner not in targets:
            targets.append(lead.owner)
        sent_any = False
        for user in targets:
            note = notify_in_app(user=user, message=msg[:255], event_key=f"{ek}:u{user.pk}")
            if note:
                sent_any = True
        if sent_any:
            if targets:
                notify_in_app(user=targets[0], message=msg[:255], event_key=ek)
            stats["reminded"] += 1
    return stats


def scan_offer_followups(*, limit: int = 200) -> dict[str, int]:
    """sent_at + 3 calendar days unanswered → sales reminder (no auto-expire)."""
    from apps.comms.models import Notification
    from apps.comms.services import notify_in_app

    stats = {"checked": 0, "reminded": 0}
    cutoff = timezone.now() - timedelta(days=3)
    qs = (
        Offer.objects.filter(status=OfferStatus.SENT, sent_at__lte=cutoff)
        .select_related("opportunity", "sent_by")
        .order_by("sent_at")[:limit]
    )
    for offer in qs:
        stats["checked"] += 1
        day_key = timezone.localdate(offer.sent_at).isoformat()
        ek = f"crm.offer.followup3d.{offer.pk}.{day_key}"
        if Notification.objects.filter(event_key=ek).exists():
            continue
        msg = _("Təklif 3 gündür cavabsız (#%(id)s)") % {"id": offer.pk}
        targets = list(sales_users())
        if offer.sent_by_id and offer.sent_by not in targets:
            targets.append(offer.sent_by)
        sent_any = False
        for user in targets:
            note = notify_in_app(user=user, message=msg[:255], event_key=f"{ek}:u{user.pk}")
            if note:
                sent_any = True
        if sent_any:
            if targets:
                notify_in_app(user=targets[0], message=msg[:255], event_key=ek)
            stats["reminded"] += 1
    return stats


def scan_crm_reminders(*, limit: int = 200) -> dict[str, int]:
    a = scan_lead_activity_reminders(limit=limit)
    b = scan_offer_followups(limit=limit)
    return {
        "leads_checked": a["checked"],
        "leads_reminded": a["reminded"],
        "offers_checked": b["checked"],
        "offers_reminded": b["reminded"],
    }


# Back-compat for pipeline.convert_offer_to_lease_draft
@transaction.atomic
def convert_offer_to_lease_draft(offer: Offer, *, actor=None):
    """Deprecated path — prefer LeaseApplicationService.create_lease_draft."""
    from apps.leases.lease_ops import refresh_lease_cached_amounts
    from apps.leases.models import Lease, LeaseStatus
    from apps.leases.services import (
        ensure_primary_lease_line,
        lock_space_for_reservation,
        next_lease_code,
        space_commercially_held,
        sync_space_from_lease,
    )

    offer = Offer.objects.select_for_update().get(pk=offer.pk)
    if offer.lease_id:
        return offer.lease
    space = offer.space
    if space is not None:
        lock_space_for_reservation(space.pk)
        if space_commercially_held(space.pk):
            raise DomainError(_("Bu sahə artıq kommersiya rezervindədir — təkrar rezerv mümkün deyil."))
    rent_rate = default_rent_rate()
    if offer.current_version_id:
        rent_rate = offer.current_version.rent_rate_per_m2
    lease = Lease.objects.create(
        code=next_lease_code(),
        party=offer.party,
        space=space,
        status=LeaseStatus.NEGOTIATION,
        rent=offer.rent_amount or 0,
        rent_rate_per_m2=rent_rate,
        service_rate_per_m2=Decimal("0"),
        deposit_months=2,
        parking_included_free=True,
        notes=offer.notes or "",
    )
    ensure_primary_lease_line(lease)
    refresh_lease_cached_amounts(lease)
    sync_space_from_lease(lease)
    offer.lease = lease
    offer.status = OfferStatus.ACCEPTED
    offer.save(update_fields=["lease", "status", "updated_at"])
    opportunity = offer.opportunity
    if opportunity and opportunity.status == OpportunityStatus.OPEN:
        opportunity.pipeline_stage = PipelineStage.LEASE_STAGE
        opportunity.save(update_fields=["pipeline_stage", "updated_at"])
    return lease
