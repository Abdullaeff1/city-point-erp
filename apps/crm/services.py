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
    def set_stage(cls, opportunity: Opportunity, *, actor, stage: str, outcome: str = "", note: str = "") -> Opportunity:
        assert_can_mutate_crm(actor)
        opportunity.pipeline_stage = stage
        if stage == PipelineStage.WON:
            opportunity.status = OpportunityStatus.WON
            opportunity.outcome = outcome or Outcome.COOPERATION_SECURED
        elif stage == PipelineStage.LOST:
            opportunity.status = OpportunityStatus.LOST
            if not outcome:
                raise DomainError(_("İtirilmiş imkan üçün nəticə məcburidir."))
            opportunity.outcome = outcome
        if note:
            opportunity.outcome_note = note
        opportunity.save()
        if opportunity.lead_id:
            lead = opportunity.lead
            lead.pipeline_stage = stage
            if opportunity.outcome:
                lead.outcome = opportunity.outcome
            if stage in (PipelineStage.WON, PipelineStage.LOST):
                lead.record_status = RecordStatus.CLOSED
            lead.save()
        log_action(actor=actor, action="crm.opportunity.stage", entity=opportunity, message=stage)
        return opportunity


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
    def send_offer(cls, version: OfferVersion, *, actor, sent_to: str = "") -> Offer:
        assert_can_mutate_crm(actor)
        from apps.workflows.models import ApprovalStatus

        # Fresh rows — UI «Təsdiqlənib» versiya approval_request-ə görədir
        offer = Offer.objects.select_for_update().get(pk=version.offer_id)
        version = OfferVersion.objects.select_for_update().get(pk=version.pk)
        if offer.current_version_id != version.pk:
            raise DomainError(_("Yalnız cari versiya göndərilə bilər."))
        req = version.approval_request
        if not req or req.status != ApprovalStatus.APPROVED:
            raise DomainError(_("Təsdiqsiz təklif göndərilə bilməz. Əvvəl rəhbərlik təsdiqi lazımdır."))
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
        log_action(
            actor=actor,
            action="crm.offer.send",
            entity=offer,
            message=f"v{version.version_number} → {offer.sent_to}",
        )
        return offer


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
            "bank_details": app.bank_details,
            "fit_out_notes": app.fit_out_notes,
            "extra_notes": app.extra_notes,
            "signer_title_name": app.signer_title_name,
            "is_legal_entity": app.is_legal_entity,
            "attachment_checklist": app.attachment_checklist or {},
        }

    @classmethod
    @transaction.atomic
    def create_from_offer(cls, offer: Offer, *, actor, data: dict | None = None) -> LeaseApplication:
        assert_can_mutate_crm(actor)
        if offer.status != OfferStatus.ACCEPTED and offer.status != OfferStatus.SENT:
            # Allow from sent (accepted by client verbally) or accepted
            if offer.status not in (OfferStatus.SENT, OfferStatus.ACCEPTED, OfferStatus.APPROVED):
                raise DomainError(_("Müraciət formu üçün təklif göndərilmiş/qəbul olunmuş olmalıdır."))
        ver = offer.current_version
        data = data or {}
        app = LeaseApplication(
            offer=offer,
            offer_version=ver,
            opportunity=offer.opportunity,
            space=offer.space,
            person_name=data.get("person_name") or (offer.party.name if offer.party_id else "")[:200],
            tax_id=(data.get("tax_id") or "")[:32],
            rent_rate_per_m2=data.get("rent_rate_per_m2") or (ver.rent_rate_per_m2 if ver else None),
            monthly_rent_net=data.get("monthly_rent_net") or (ver.monthly_rent_net if ver else None),
            space_label=(data.get("space_label") or (str(offer.space) if offer.space_id else ""))[:128],
            floor_label=(data.get("floor_label") or "")[:64],
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
        ):
            if field in data:
                setattr(app, field, data[field])
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
        for field, value in data.items():
            if hasattr(app, field) and field not in ("status", "lease", "id"):
                setattr(app, field, value)
        app.form_snapshot = cls._snapshot(app)
        app.save()
        return app

    @classmethod
    @transaction.atomic
    def submit_to_accounting(cls, app: LeaseApplication, *, actor) -> LeaseApplication:
        assert_can_mutate_crm(actor)
        if app.status not in (
            LeaseApplicationStatus.DRAFT,
            LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
        ):
            raise DomainError(_("Müraciət göndərilə bilməz."))
        app.form_snapshot = cls._snapshot(app)
        app.status = LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING
        app.submitted_by = actor
        app.submitted_at = timezone.now()
        app.save()
        log_action(actor=actor, action="crm.lease_app.submit", entity=app, message=str(app.pk))
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
    @transaction.atomic
    def create_lease_draft(cls, app: LeaseApplication, *, actor) -> LeaseApplication:
        assert_can_review_lease_application(actor)
        from apps.leases.lease_ops import refresh_lease_cached_amounts
        from apps.leases.models import Lease, LeaseStatus
        from apps.leases.services import next_lease_code

        if app.lease_id:
            return app
        party = app.offer.party if app.offer_id else None
        if party is None:
            raise DomainError(_("Party yoxdur — lease yaradıla bilməz."))
        rate = app.rent_rate_per_m2 or default_rent_rate()
        rent = app.monthly_rent_net or 0
        lease = Lease.objects.create(
            code=next_lease_code(),
            party=party,
            space=app.space,
            status=LeaseStatus.DRAFT,
            rent=rent,
            rent_rate_per_m2=rate,
            service_rate_per_m2=Decimal("0"),
            deposit_months=2,
            parking_included_free=True,
            start_date=app.lease_start,
            end_date=app.lease_end,
            notes=app.extra_notes or app.sales_notes or "",
        )
        refresh_lease_cached_amounts(lease)
        app.lease = lease
        app.status = LeaseApplicationStatus.LEASE_DRAFT_CREATED
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        app.save()
        if app.offer_id:
            offer = app.offer
            offer.lease = lease
            offer.status = OfferStatus.ACCEPTED
            offer.save(update_fields=["lease", "status", "updated_at"])
            opp = offer.opportunity
            if opp:
                opp.status = OpportunityStatus.WON
                opp.pipeline_stage = PipelineStage.LEASE_STAGE
                opp.outcome = Outcome.COOPERATION_SECURED
                opp.save()
        log_action(actor=actor, action="crm.lease_app.lease_draft", entity=app, message=lease.code)
        return app

    @classmethod
    @transaction.atomic
    def mark_signed_and_complete(cls, app: LeaseApplication, *, actor, upsert_party: bool = True) -> LeaseApplication:
        assert_can_review_lease_application(actor)
        from apps.parties.resolvers import party_for_company
        from apps.residents.models import ResidentCompany

        app.status = LeaseApplicationStatus.SIGNED_DOCUMENTS_RECEIVED
        app.reviewed_by = actor
        app.reviewed_at = timezone.now()
        app.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        if upsert_party and app.person_name:
            # Prefer linking existing resident company by tax_id / name after signed contract
            company = None
            if app.tax_id:
                company = ResidentCompany.objects.filter(voen=app.tax_id).first()
            if company is None and app.person_name:
                company = ResidentCompany.objects.filter(name__iexact=app.person_name).first()
            if company is not None:
                party_for_company(company, ensure=True)
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
    """1 calendar day without activity → sales reminder (idempotent)."""
    from apps.comms.models import Notification
    from apps.comms.services import notify_in_app

    stats = {"checked": 0, "reminded": 0}
    cutoff = timezone.now() - timedelta(days=1)
    qs = (
        Lead.objects.filter(record_status=RecordStatus.OPEN)
        .exclude(qualification=Qualification.NON_POTENTIAL)
        .order_by("created_at")[:limit]
    )
    for lead in qs:
        stats["checked"] += 1
        created = lead.created_at
        if created > cutoff:
            continue
        if lead.activities.exclude(activity_type=ActivityType.STATUS_CHANGE).exists():
            continue
        day_key = timezone.localdate(created).isoformat()
        ek = f"crm.lead.idle1d.{lead.pk}.{day_key}"
        if Notification.objects.filter(event_key=ek).exists():
            continue
        msg = _("Lid 1 gündür aktivliksiz: %(name)s") % {"name": str(lead)}
        targets = list(sales_users())
        if lead.owner_id and lead.owner not in targets:
            targets.append(lead.owner)
        sent_any = False
        for user in targets:
            note = notify_in_app(user=user, message=msg[:255], event_key=f"{ek}:u{user.pk}")
            if note:
                sent_any = True
        if sent_any:
            # Anchor key so re-scan skips even if users list empty next time
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
def convert_offer_to_lease_draft(offer: Offer):
    """Deprecated path — prefer LeaseApplicationService.create_lease_draft."""
    from apps.leases.lease_ops import refresh_lease_cached_amounts
    from apps.leases.models import Lease, LeaseStatus
    from apps.leases.services import next_lease_code

    if offer.lease_id:
        return offer.lease
    space = offer.space
    rent_rate = default_rent_rate()
    if offer.current_version_id:
        rent_rate = offer.current_version.rent_rate_per_m2
    lease = Lease.objects.create(
        code=next_lease_code(),
        party=offer.party,
        space=space,
        status=LeaseStatus.DRAFT,
        rent=offer.rent_amount or 0,
        rent_rate_per_m2=rent_rate,
        service_rate_per_m2=Decimal("0"),
        deposit_months=2,
        parking_included_free=True,
        notes=offer.notes or "",
    )
    refresh_lease_cached_amounts(lease)
    offer.lease = lease
    offer.status = OfferStatus.ACCEPTED
    offer.save(update_fields=["lease", "status", "updated_at"])
    opportunity = offer.opportunity
    if opportunity and opportunity.status == OpportunityStatus.OPEN:
        opportunity.status = OpportunityStatus.WON
        opportunity.save(update_fields=["status", "updated_at"])
    return lease
