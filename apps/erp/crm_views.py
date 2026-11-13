"""ERP CRM / Satış views — leads, opportunities, offers, lease applications, reports."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.mixins import CrmAccessMixin
from apps.core.services import DomainError
from apps.crm.access import can_approve_offer, can_mutate_crm, can_review_lease_application
from apps.crm.models import (
    ActivityType,
    Lead,
    LeadSource,
    LeaseApplication,
    LeaseApplicationStatus,
    Offer,
    OfferStatus,
    OfferVersion,
    Opportunity,
    Outcome,
    PipelineStage,
    Qualification,
    RecordStatus,
)
from apps.crm.reports import build_crm_report, export_crm_xlsx
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    LeaseApplicationService,
    find_duplicate_leads,
)


def _dec(raw):
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _int(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class CrmLeadListView(CrmAccessMixin, ListView):
    template_name = "erp/crm_leads.html"
    context_object_name = "leads"
    paginate_by = 50

    def get_queryset(self):
        qs = Lead.objects.select_related("interested_space", "party", "owner").order_by("-created_at")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(
                Q(company_name__icontains=q)
                | Q(full_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )
        for field in ("source", "qualification", "pipeline_stage", "record_status", "outcome"):
            val = self.request.GET.get(field)
            if val:
                qs = qs.filter(**{field: val})
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "can_mutate": can_mutate_crm(self.request.user),
                "sources": LeadSource.choices,
                "qualifications": Qualification.choices,
                "stages": PipelineStage.choices,
                "record_statuses": RecordStatus.choices,
                "outcomes": Outcome.choices,
                "filters": self.request.GET,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_crm(request.user):
            messages.error(request, "CRM dəyişiklik icazəniz yoxdur.")
            return redirect("erp:crm_leads")
        action = request.POST.get("action")
        try:
            if action == "create":
                data = {
                    "company_name": request.POST.get("company_name", ""),
                    "full_name": request.POST.get("full_name", ""),
                    "phone": request.POST.get("phone", ""),
                    "email": request.POST.get("email", ""),
                    "source": request.POST.get("source") or LeadSource.MANUAL,
                    "source_note": request.POST.get("source_note", ""),
                    "inquired_at": parse_date(request.POST.get("inquired_at") or "") or timezone.localdate(),
                    "min_area_m2": _dec(request.POST.get("min_area_m2")),
                    "max_area_m2": _dec(request.POST.get("max_area_m2")),
                    "employee_count": _int(request.POST.get("employee_count")),
                    "message": request.POST.get("message", ""),
                    "initial_note": request.POST.get("initial_note", ""),
                    "contact_missing_reason": request.POST.get("contact_missing_reason", ""),
                }
                force = request.POST.get("force_create") == "1"
                dups = find_duplicate_leads(
                    phone=data["phone"], email=data["email"], company_name=data["company_name"]
                )
                if dups and not force:
                    messages.warning(
                        request,
                        f"Oxşar lid tapıldı (#{dups[0].pk}). Yenə də yaratmaq üçün 'Təkrar yarat' seçin və ya mövcud lidə activity əlavə edin.",
                    )
                    request.session["crm_pending_lead"] = {k: str(v) if v is not None else "" for k, v in data.items()}
                    return redirect("erp:crm_leads")
                lead = CrmLeadService.create_lead(actor=request.user, data=data)
                messages.success(request, f"Lid #{lead.pk} yaradıldı.")
                return redirect("erp:crm_lead_detail", pk=lead.pk)
            lead = get_object_or_404(Lead, pk=request.POST.get("lead_id"))
            if action == "qualify":
                CrmLeadService.update_lead(
                    lead, actor=request.user, data={"qualification": Qualification.POTENTIAL}
                )
                messages.success(request, "Lid potensial sayıldı.")
            elif action == "opportunity":
                if lead.qualification != Qualification.POTENTIAL:
                    CrmLeadService.update_lead(
                        lead, actor=request.user, data={"qualification": Qualification.POTENTIAL}
                    )
                opp = CrmOpportunityService.create_from_lead(lead, actor=request.user)
                messages.success(request, f"İmkan #{opp.pk} yaradıldı.")
                return redirect("erp:crm_opportunity_detail", pk=opp.pk)
        except DomainError as exc:
            messages.error(request, str(exc))
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("erp:crm_leads")


class CrmLeadDetailView(CrmAccessMixin, DetailView):
    model = Lead
    template_name = "erp/crm_lead_detail.html"
    context_object_name = "lead"

    def get_queryset(self):
        return Lead.objects.select_related("owner", "interested_space", "party").prefetch_related(
            "activities", "opportunities"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "can_mutate": can_mutate_crm(self.request.user),
                "activity_types": ActivityType.choices,
                "qualifications": Qualification.choices,
                "stages": PipelineStage.choices,
                "record_statuses": RecordStatus.choices,
                "outcomes": Outcome.choices,
                "sources": LeadSource.choices,
                "duplicates": find_duplicate_leads(
                    phone=self.object.phone,
                    email=self.object.email,
                    company_name=self.object.company_name,
                    exclude_pk=self.object.pk,
                ),
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        lead = self.get_object()
        if not can_mutate_crm(request.user):
            messages.error(request, "CRM dəyişiklik icazəniz yoxdur.")
            return redirect("erp:crm_lead_detail", pk=lead.pk)
        action = request.POST.get("action")
        try:
            if action == "activity":
                CrmLeadService.add_activity(
                    lead,
                    actor=request.user,
                    activity_type=request.POST.get("activity_type") or ActivityType.NOTE,
                    body=request.POST.get("body", ""),
                )
                messages.success(request, "Aktivlik əlavə olundu.")
            elif action == "update":
                CrmLeadService.update_lead(
                    lead,
                    actor=request.user,
                    data={
                        "company_name": request.POST.get("company_name", lead.company_name),
                        "full_name": request.POST.get("full_name", lead.full_name),
                        "phone": request.POST.get("phone", lead.phone),
                        "email": request.POST.get("email", lead.email),
                        "source": request.POST.get("source") or lead.source,
                        "source_note": request.POST.get("source_note", lead.source_note),
                        "qualification": request.POST.get("qualification") or lead.qualification,
                        "qualification_reason": request.POST.get("qualification_reason", ""),
                        "pipeline_stage": request.POST.get("pipeline_stage") or lead.pipeline_stage,
                        "record_status": request.POST.get("record_status") or lead.record_status,
                        "outcome": request.POST.get("outcome", lead.outcome),
                        "outcome_note": request.POST.get("outcome_note", lead.outcome_note),
                        "message": request.POST.get("message", lead.message),
                        "min_area_m2": _dec(request.POST.get("min_area_m2")),
                        "max_area_m2": _dec(request.POST.get("max_area_m2")),
                        "employee_count": _int(request.POST.get("employee_count")),
                    },
                )
                messages.success(request, "Lid yeniləndi.")
            elif action == "opportunity":
                if lead.qualification != Qualification.POTENTIAL:
                    CrmLeadService.update_lead(
                        lead, actor=request.user, data={"qualification": Qualification.POTENTIAL}
                    )
                opp = CrmOpportunityService.create_from_lead(lead, actor=request.user)
                messages.success(request, f"İmkan #{opp.pk} yaradıldı.")
                return redirect("erp:crm_opportunity_detail", pk=opp.pk)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("erp:crm_lead_detail", pk=lead.pk)


class CrmOpportunityListView(CrmAccessMixin, ListView):
    template_name = "erp/crm_opportunities.html"
    context_object_name = "opportunities"

    def get_queryset(self):
        return Opportunity.objects.select_related("lead", "party", "space", "owner").order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_mutate"] = can_mutate_crm(self.request.user)
        return ctx


class CrmOpportunityDetailView(CrmAccessMixin, DetailView):
    model = Opportunity
    template_name = "erp/crm_opportunity_detail.html"
    context_object_name = "opportunity"

    def get_queryset(self):
        return Opportunity.objects.select_related("lead", "party", "space").prefetch_related("offers")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "can_mutate": can_mutate_crm(self.request.user),
                "stages": PipelineStage.choices,
                "outcomes": Outcome.choices,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        opp = self.get_object()
        if not can_mutate_crm(request.user):
            messages.error(request, "CRM dəyişiklik icazəniz yoxdur.")
            return redirect("erp:crm_opportunity_detail", pk=opp.pk)
        action = request.POST.get("action")
        try:
            if action == "stage":
                CrmOpportunityService.set_stage(
                    opp,
                    actor=request.user,
                    stage=request.POST.get("pipeline_stage") or opp.pipeline_stage,
                    outcome=request.POST.get("outcome") or "",
                    note=request.POST.get("outcome_note") or "",
                )
                messages.success(request, "Mərhələ yeniləndi.")
            elif action == "create_offer":
                if not opp.party_id:
                    from apps.parties.models import Party, PartyRole, PartyRoleCode

                    name = ((opp.lead.company_name if opp.lead_id else "") or opp.title)[:200]
                    party = Party.objects.create(legal_name=name or f"Opp #{opp.pk}")
                    PartyRole.objects.get_or_create(
                        party=party, role=PartyRoleCode.PROSPECT, defaults={"is_primary": True}
                    )
                    opp.party = party
                    opp.save(update_fields=["party", "updated_at"])
                offer = CrmOfferService.create_offer(
                    actor=request.user,
                    opportunity=opp,
                    party=opp.party,
                    space=opp.space,
                    area_m2=_dec(request.POST.get("area_m2")) or opp.expected_area,
                    rent_rate_per_m2=_dec(request.POST.get("rent_rate_per_m2")),
                    discount_percent=_dec(request.POST.get("discount_percent")) or Decimal("0"),
                    notes=request.POST.get("notes") or "",
                )
                messages.success(request, f"Təklif #{offer.pk} yaradıldı.")
                return redirect("erp:crm_offer_detail", pk=offer.pk)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("erp:crm_opportunity_detail", pk=opp.pk)


class CrmOfferListView(CrmAccessMixin, ListView):
    template_name = "erp/crm_offers.html"
    context_object_name = "offers"

    def get_queryset(self):
        return Offer.objects.select_related(
            "party", "space", "opportunity", "lease", "current_version"
        ).order_by("-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_mutate"] = can_mutate_crm(self.request.user)
        ctx["can_approve"] = can_approve_offer(self.request.user)
        return ctx


class CrmOfferDetailView(CrmAccessMixin, DetailView):
    model = Offer
    template_name = "erp/crm_offer_detail.html"
    context_object_name = "offer"

    def get_queryset(self):
        return Offer.objects.select_related(
            "party", "space", "opportunity", "current_version", "lease"
        ).prefetch_related("versions")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "can_mutate": can_mutate_crm(self.request.user),
                "can_approve": can_approve_offer(self.request.user),
                "versions": self.object.versions.select_related("approval_request").all(),
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        offer = self.get_object()
        action = request.POST.get("action")
        try:
            if action == "new_version":
                if not can_mutate_crm(request.user):
                    raise DomainError("İcazə yoxdur.")
                CrmOfferService.create_new_version(
                    offer,
                    actor=request.user,
                    data={
                        "rent_rate_per_m2": _dec(request.POST.get("rent_rate_per_m2")),
                        "area_m2": _dec(request.POST.get("area_m2")),
                        "discount_percent": _dec(request.POST.get("discount_percent")) or Decimal("0"),
                        "discount_note": request.POST.get("discount_note", ""),
                        "notes": request.POST.get("notes", ""),
                        "valid_until": parse_date(request.POST.get("valid_until") or "") or None,
                    },
                )
                messages.success(request, "Yeni versiya yaradıldı.")
            elif action == "request_approval":
                version = get_object_or_404(OfferVersion, pk=request.POST.get("version_id"), offer=offer)
                CrmOfferService.request_send_approval(version, actor=request.user)
                messages.success(request, "Təsdiq sorğusu göndərildi.")
            elif action == "decide":
                version = get_object_or_404(OfferVersion, pk=request.POST.get("version_id"), offer=offer)
                approved = request.POST.get("approved") == "1"
                CrmOfferService.decide_approval(
                    version,
                    actor=request.user,
                    approved=approved,
                    comment=request.POST.get("comment", ""),
                )
                messages.success(request, "Təsdiq edildi." if approved else "Rədd edildi.")
            elif action == "send":
                version = get_object_or_404(OfferVersion, pk=request.POST.get("version_id"), offer=offer)
                CrmOfferService.send_offer(
                    version, actor=request.user, sent_to=request.POST.get("sent_to", "")
                )
                messages.success(request, "Təklif göndərildi.")
            elif action == "lease_application":
                app = LeaseApplicationService.create_from_offer(offer, actor=request.user)
                messages.success(request, f"Müraciət formu #{app.pk} yaradıldı.")
                return redirect("erp:crm_lease_application_detail", pk=app.pk)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("erp:crm_offer_detail", pk=offer.pk)


class CrmLeaseApplicationListView(CrmAccessMixin, ListView):
    template_name = "erp/crm_lease_applications.html"
    context_object_name = "applications"

    def get_queryset(self):
        qs = LeaseApplication.objects.select_related(
            "offer", "space", "lease", "opportunity", "submitted_by"
        ).order_by("-created_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        # Accountant queue focus
        if can_review_lease_application(self.request.user) and self.request.GET.get("queue") == "1":
            qs = qs.filter(
                status__in=(
                    LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING,
                    LeaseApplicationStatus.UNDER_REVIEW,
                    LeaseApplicationStatus.LEASE_DRAFT_CREATED,
                )
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_mutate"] = can_mutate_crm(self.request.user)
        ctx["can_review"] = can_review_lease_application(self.request.user)
        ctx["statuses"] = LeaseApplicationStatus.choices
        return ctx


class CrmLeaseApplicationDetailView(CrmAccessMixin, DetailView):
    model = LeaseApplication
    template_name = "erp/crm_lease_application_detail.html"
    context_object_name = "application"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_mutate"] = can_mutate_crm(self.request.user)
        ctx["can_review"] = can_review_lease_application(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        app = self.get_object()
        action = request.POST.get("action")
        try:
            if action == "update":
                LeaseApplicationService.update_draft(
                    app,
                    actor=request.user,
                    data={
                        "person_name": request.POST.get("person_name", ""),
                        "tax_id": request.POST.get("tax_id", ""),
                        "legal_address": request.POST.get("legal_address", ""),
                        "actual_address": request.POST.get("actual_address", ""),
                        "floor_label": request.POST.get("floor_label", ""),
                        "space_label": request.POST.get("space_label", ""),
                        "use_purpose": request.POST.get("use_purpose", ""),
                        "rent_rate_per_m2": _dec(request.POST.get("rent_rate_per_m2")),
                        "monthly_rent_net": _dec(request.POST.get("monthly_rent_net")),
                        "deposit_amount": _dec(request.POST.get("deposit_amount")),
                        "rent_free_note": request.POST.get("rent_free_note", ""),
                        "cleaning_included": request.POST.get("cleaning_included") == "on",
                        "tea_service_included": request.POST.get("tea_service_included") == "on",
                        "lease_start": parse_date(request.POST.get("lease_start") or "") or None,
                        "lease_end": parse_date(request.POST.get("lease_end") or "") or None,
                        "bank_details": request.POST.get("bank_details", ""),
                        "fit_out_notes": request.POST.get("fit_out_notes", ""),
                        "extra_notes": request.POST.get("extra_notes", ""),
                        "signer_title_name": request.POST.get("signer_title_name", ""),
                        "sales_notes": request.POST.get("sales_notes", ""),
                        "attachment_checklist": {
                            "voen": request.POST.get("chk_voen") == "on",
                            "registry": request.POST.get("chk_registry") == "on",
                            "bank": request.POST.get("chk_bank") == "on",
                        },
                    },
                )
                messages.success(request, "Forma yeniləndi.")
            elif action == "submit":
                LeaseApplicationService.submit_to_accounting(app, actor=request.user)
                messages.success(request, "Mühasibə göndərildi.")
            elif action == "accept":
                LeaseApplicationService.accountant_accept(
                    app, actor=request.user, notes=request.POST.get("accountant_notes", "")
                )
                messages.success(request, "Baxışa alındı.")
            elif action == "return":
                LeaseApplicationService.accountant_return(
                    app, actor=request.user, notes=request.POST.get("accountant_notes", "")
                )
                messages.success(request, "Düzəlişə qaytarıldı.")
            elif action == "lease_draft":
                LeaseApplicationService.create_lease_draft(app, actor=request.user)
                messages.success(request, f"İcarə qaralaması: {app.lease.code if app.lease_id else ''}")
            elif action == "complete":
                LeaseApplicationService.mark_signed_and_complete(app, actor=request.user)
                messages.success(request, "Tamamlandı — imzalanmış sənədlər qeyd olundu.")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("erp:crm_lease_application_detail", pk=app.pk)


class CrmReportView(CrmAccessMixin, TemplateView):
    template_name = "erp/crm_reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = {
            "date_from": parse_date(self.request.GET.get("date_from") or "") or None,
            "date_to": parse_date(self.request.GET.get("date_to") or "") or None,
            "source": self.request.GET.get("source") or "",
            "qualification": self.request.GET.get("qualification") or "",
            "pipeline_stage": self.request.GET.get("pipeline_stage") or "",
            "record_status": self.request.GET.get("record_status") or "",
            "outcome": self.request.GET.get("outcome") or "",
        }
        ctx["report"] = build_crm_report(params)
        ctx["filters"] = self.request.GET
        ctx["sources"] = LeadSource.choices
        ctx["qualifications"] = Qualification.choices
        ctx["stages"] = PipelineStage.choices
        ctx["record_statuses"] = RecordStatus.choices
        ctx["outcomes"] = Outcome.choices
        return ctx


class CrmReportExportView(CrmAccessMixin, View):
    def get(self, request, *args, **kwargs):
        params = {
            "date_from": parse_date(request.GET.get("date_from") or "") or None,
            "date_to": parse_date(request.GET.get("date_to") or "") or None,
            "source": request.GET.get("source") or "",
            "qualification": request.GET.get("qualification") or "",
            "pipeline_stage": request.GET.get("pipeline_stage") or "",
            "record_status": request.GET.get("record_status") or "",
            "outcome": request.GET.get("outcome") or "",
        }
        data = export_crm_xlsx(params)
        resp = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="crm_report.xlsx"'
        return resp
