"""Rəhbərlik (MANAGEMENT) ERP modul hub — şöbə portalı yox, ERP RO nəticə kartları."""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import Role


def build_management_hub(user) -> dict:
    """Return hub_modules + approval strip counts for the management dashboard."""
    today = timezone.localdate()

    from apps.workflows.models import ApprovalRequest, ApprovalStatus
    from apps.tickets.models import OPEN_STATUSES
    from apps.tickets.access import tickets_visible_to
    from apps.residents.models import ResidentCompany, ResidentEmployee, RapidCardSwipeAlert, ShaftAccessAlert
    from apps.residents.access import currently_inside_employee_rows
    from apps.reception.models import GuestVisit, VisitStatus
    from apps.documents.models import Document
    from apps.procurement.models import PurchaseRequest, PRStatus
    from apps.crm.dashboard import open_leads_qs
    from apps.property.models import Space
    from apps.warehouse.models import Stock

    pending = ApprovalRequest.objects.filter(
        workflow_code__in=(
            "crm.offer.send",
            "finance.payment",
            "procurement.pr",
            "procurement.commitment",
            "document.approve",
        ),
        status=ApprovalStatus.PENDING,
    )
    pending_offers = pending.filter(workflow_code="crm.offer.send").count()
    pending_payments = pending.filter(workflow_code="finance.payment").count()
    pending_procurement = pending.filter(
        workflow_code__in=("procurement.pr", "procurement.commitment")
    ).count()
    pending_documents = pending.filter(workflow_code="document.approve").count()

    open_list = list(tickets_visible_to(user).filter(status__in=OPEN_STATUSES))
    open_tickets = len(open_list)
    sla_risk = sum(1 for t in open_list if getattr(t, "sla_risk", False))

    employees_inside = len(currently_inside_employee_rows(today))
    guests_inside = GuestVisit.objects.filter(
        scheduled_for=today, status=VisitStatus.INSIDE
    ).count()
    people_inside = employees_inside + guests_inside
    cp = ResidentCompany.objects.filter(slug="city-point").first()
    internal_staff = (
        ResidentEmployee.objects.filter(company=cp, is_active=True).count() if cp else 0
    )

    doc_count = Document.objects.count()
    open_prs = PurchaseRequest.objects.exclude(status=PRStatus.REJECTED).count()

    security_alerts = (
        RapidCardSwipeAlert.objects.filter(acknowledged_at__isnull=True).count()
        + ShaftAccessAlert.objects.filter(acknowledged_at__isnull=True).count()
    )

    open_leads = open_leads_qs().count()
    active_residents = ResidentCompany.objects.filter(
        status="active", is_internal=False
    ).count()
    spaces_count = Space.objects.count()
    stock_rows = Stock.objects.count()

    modules = [
        {
            "key": "hr",
            "title": _("HR & Employees"),
            "subtitle": _("Əməkdaşlar, davamiyyət"),
            "icon": "users",
            "url": reverse("erp:hr_dashboard"),
            "kpi": internal_staff,
            "kpi_label": _("daxili işçi"),
            "meta": f"{people_inside} {_('içəridə')}",
        },
        {
            "key": "residents",
            "title": _("Rezidentlər"),
            "subtitle": _("Şirkətlər, kart, əməkdaşlar"),
            "icon": "building",
            "url": reverse("erp:residents"),
            "kpi": active_residents,
            "kpi_label": _("aktiv"),
            "meta": "",
        },
        {
            "key": "crm",
            "title": _("CRM"),
            "subtitle": _("Müştərilər, əlaqələr, satış"),
            "icon": "handshake",
            "url": reverse("erp:crm_leads"),
            "kpi": open_leads,
            "kpi_label": _("açıq lid"),
            "meta": "",
        },
        {
            "key": "documents",
            "title": _("Documents"),
            "subtitle": _("Sənədlər, müqavilələr, arxiv"),
            "icon": "file-text",
            "url": reverse("erp:documents"),
            "kpi": doc_count,
            "kpi_label": _("sənəd"),
            "meta": "",
        },
        {
            "key": "property",
            "title": _("Property"),
            "subtitle": _("Binalar, sahələr, icarələr"),
            "icon": "building-2",
            "url": reverse("erp:spaces"),
            "kpi": spaces_count,
            "kpi_label": _("sahə"),
            "meta": "",
        },
        {
            "key": "helpdesk",
            "title": _("Helpdesk"),
            "subtitle": _("Müraciətlər, SLA, tapşırıqlar"),
            "icon": "ticket",
            "url": reverse("erp:tickets"),
            "kpi": open_tickets,
            "kpi_label": _("açıq ticket"),
            "meta": f"{sla_risk} {_('SLA risk')}",
        },
        {
            "key": "inventory",
            "title": _("Inventory"),
            "subtitle": _("Anbar, avadanlıq, inventar"),
            "icon": "package",
            "url": reverse("erp:warehouse"),
            "kpi": stock_rows,
            "kpi_label": _("stok sətiri"),
            "meta": "",
        },
        {
            "key": "procurement",
            "title": _("Procurement"),
            "subtitle": _("Satınalma, təchizatçılar"),
            "icon": "shopping-cart",
            "url": reverse("erp:procurement"),
            "kpi": open_prs,
            "kpi_label": _("sorğu"),
            "meta": "",
        },
        {
            "key": "accounting",
            "title": _("Accounting"),
            "subtitle": _("Maliyyə, ödənişlər, hesabatlar"),
            "icon": "calculator",
            "url": reverse("erp:payment_approvals"),
            "kpi": pending_payments + pending_offers + pending_procurement + pending_documents,
            "kpi_label": _("gözləyən təsdiq"),
            "meta": "",
        },
        {
            "key": "security",
            "title": _("Security"),
            "subtitle": _("Giriş-çıxış, təhlükəsizlik"),
            "icon": "shield-check",
            "url": reverse("erp:people_inside"),
            "kpi": people_inside,
            "kpi_label": _("içəridə"),
            "meta": f"{security_alerts} {_('açıq alert')}",
        },
        {
            "key": "reports",
            "title": _("Reports"),
            "subtitle": _("Analitika, statistika, KPI"),
            "icon": "bar-chart-3",
            "url": reverse("erp:reports"),
            "kpi": None,
            "kpi_label": "",
            "meta": _("İdarə hesabatları"),
        },
    ]

    return {
        "is_management_hub": True,
        "is_sales_dashboard": False,
        "hub_modules": modules,
        "pending_offers": pending_offers,
        "pending_payments": pending_payments,
        "pending_procurement": pending_procurement,
        "pending_documents": pending_documents,
        "pending_total": (
            pending_offers + pending_payments + pending_procurement + pending_documents
        ),
        "show_approvals": True,
        "people_inside_count": people_inside,
        "security_alerts": security_alerts,
    }


def is_management_user(user) -> bool:
    return getattr(user, "role", None) == Role.MANAGEMENT
