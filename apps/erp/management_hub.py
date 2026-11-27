"""Rəhbərlik (MANAGEMENT) ERP hub — qərar növbəsi + bina KPI (as-of Asia/Baku)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.finance.ap_services import WF_SUPPLIER_PAYMENT


def building_register_snapshot(*, as_of=None) -> dict:
    """Bina kartları üçün əməliyyat reyestri (Space.register_status + resident).

    Formal Lease sətirləri natamam ola bilər; sahə siyahısı və rezident
    kartları eyni reyestr seçicisini istifadə edir. ``as_of`` bu gün üçün
    oxunur (tarix göstəricisi ilə eyni Asia/Baku günü).
    """
    from apps.property.models import OperationalStatus, Space

    del as_of  # current register snapshot; date shown on dashboard separately
    spaces = list(Space.objects.select_related("resident", "floor"))
    denom_ids: list[int] = []
    denom_m2 = Decimal("0")
    occupied_ids: list[int] = []
    occupied_m2 = Decimal("0")
    resident_ids: set[int] = set()

    for space in spaces:
        if space.operational_status == OperationalStatus.BLOCKED:
            continue
        area = Decimal(str(space.rentable_area_m2 or space.area_m2 or 0))
        if area <= 0:
            continue
        denom_ids.append(space.pk)
        denom_m2 += area
        if space.register_status != "occupied":
            continue
        occupied_ids.append(space.pk)
        occupied_m2 += area
        if space.resident_id:
            resident_ids.add(int(space.resident_id))

    return {
        "denominator_count": len(denom_ids),
        "denominator_ids": denom_ids,
        "total_m2": float(denom_m2),
        "occupied_count": len(occupied_ids),
        "occupied_ids": occupied_ids,
        "occupied_m2": float(occupied_m2),
        "occupying_resident_ids": sorted(resident_ids),
        "occupying_resident_count": len(resident_ids),
        "inventory_types": _(
            "Bloklanmamış, rentable_area/area > 0 olan kommersiya sahələri"
        ),
    }


def build_management_hub(user) -> dict:
    """Return decision queues, building KPIs, events, and shortcuts for Management."""
    today = timezone.localdate()

    from apps.workflows.models import ApprovalRequest, ApprovalStatus
    from apps.erp.exec_reports import (
        build_finance_report,
        build_fm_report,
        build_property_report,
        parse_report_params,
    )
    from apps.leases.models import Lease, LeaseStatus
    from apps.maintenance.models import MaintenancePlan
    from apps.crm.models import LeadActivity
    from apps.crm.dashboard import available_spaces_qs
    from apps.residents.models import RapidCardSwipeAlert, ShaftAccessAlert

    params = parse_report_params({"date_to": today.isoformat()})
    prop = build_property_report(params)
    fm = build_fm_report(params)
    fin = build_finance_report(params)
    as_of = prop.get("as_of") or today
    as_of_q = as_of.isoformat()

    pending = ApprovalRequest.objects.filter(
        workflow_code__in=(
            "crm.offer.send",
            "finance.payment",
            WF_SUPPLIER_PAYMENT,
            "procurement.pr",
            "procurement.commitment",
            "document.approve",
        ),
        status=ApprovalStatus.PENDING,
    )
    pending_offers = pending.filter(workflow_code="crm.offer.send").count()
    pending_payments = pending.filter(workflow_code="finance.payment").count()
    pending_ap_payments = pending.filter(workflow_code=WF_SUPPLIER_PAYMENT).count()
    pending_procurement = pending.filter(
        workflow_code__in=("procurement.pr", "procurement.commitment")
    ).count()
    pending_documents = pending.filter(workflow_code="document.approve").count()
    pending_total = (
        pending_offers
        + pending_payments
        + pending_ap_payments
        + pending_procurement
        + pending_documents
    )

    security_alerts = (
        RapidCardSwipeAlert.objects.filter(acknowledged_at__isnull=True).count()
        + ShaftAccessAlert.objects.filter(acknowledged_at__isnull=True).count()
    )

    pay_base = reverse("erp:payment_approvals")
    approvals_url = reverse("erp:approvals")
    spaces_url = reverse("erp:spaces")
    residents_url = reverse("erp:residents")
    ready_qs, _conflicts = available_spaces_qs(today=as_of)
    ready_count = ready_qs.count()

    decision_queue = [
        {
            "key": "crm_offers",
            "title": _("Kommersiya təklifləri"),
            "count": pending_offers,
            "url": f"{approvals_url}?workflow=crm.offer.send",
            "action": _("Təsdiq / rədd"),
            "meta": "",
        },
        {
            "key": "documents",
            "title": _("Sənəd təsdiqi"),
            "count": pending_documents,
            "url": f"{approvals_url}?workflow=document.approve",
            "action": _("Təsdiq / rədd"),
            "meta": "",
        },
        {
            "key": "procurement",
            "title": _("Satınalma / öhdəlik"),
            "count": pending_procurement,
            "url": f"{approvals_url}?workflow=procurement",
            "action": _("Təsdiq / rədd"),
            "meta": "",
        },
        {
            "key": "ar_payments",
            "title": _("Debitor ödəniş"),
            "count": pending_payments,
            "url": f"{pay_base}?queue=ar",
            "action": _("Təsdiq et"),
            "meta": _("AR"),
        },
        {
            "key": "ap_payments",
            "title": _("Kreditor ödəniş"),
            "count": pending_ap_payments,
            "url": f"{pay_base}?queue=ap",
            "action": _("İcazə ver"),
            "meta": _("AP · settlement Mühasibdə"),
        },
    ]

    # Building cards — Space register (matches /erp/spaces/?status=…); m² secondary
    inventory = building_register_snapshot(as_of=as_of)
    inventory_types = inventory["inventory_types"]
    total_m2 = Decimal(str(inventory["total_m2"] or 0))
    occupied_m2 = Decimal(str(inventory["occupied_m2"] or 0))
    occupancy_rule = _(
        "Reyestr: Space.register_status=occupied m² / bloklanmamış rentable m² "
        "(KPI kartları ilə eyni mənbə; Lease as-of deyil)"
    )
    if total_m2 > 0:
        occupancy_display = f"{round(float(100 * occupied_m2 / total_m2), 1)}%"
    else:
        occupancy_display = "—"
    building_kpis = [
        {
            "key": "residents",
            "label": _("Rezident şirkətlər"),
            "value": inventory["occupying_resident_count"],
            "unit": "",
            "url": f"{residents_url}?occupying=1&as_of={as_of_q}",
            "meta": _("as-of %(d)s · unikal şirkət") % {"d": as_of.strftime("%d.%m.%Y")},
            "definition": _(
                "Dolu sahələrin Space.resident bağlantısı üzrə unikal "
                "ResidentCompany. Bir şirkət 3 ofis tutsa 1 sayılır."
            ),
        },
        {
            "key": "spaces_total",
            "label": _("Ümumi sahələr"),
            "value": inventory["denominator_count"],
            "unit": "",
            "url": f"{spaces_url}?mgmt=rentable&as_of={as_of_q}",
            "meta": _("%(m2)s m² · rentable") % {"m2": inventory["total_m2"]},
            "definition": inventory_types,
        },
        {
            "key": "spaces_occupied",
            "label": _("Dolu sahələr"),
            "value": inventory["occupied_count"],
            "unit": "",
            "url": f"{spaces_url}?status=occupied",
            "meta": _("%(m2)s m² · reyestr") % {"m2": inventory["occupied_m2"]},
            "definition": _(
                "Space.register_status=occupied (aktiv icarə / commercial active|notice). "
                "Gələcək rezervasiya və bloklanmış sahə daxil deyil."
            ),
        },
        {
            "key": "spaces_ready",
            "label": _("İcarəyə hazır boş sahələr"),
            "value": ready_count,
            "unit": "",
            "url": reverse("erp:crm_available_spaces"),
            "meta": _("kommersiya VACANT · rezerv/blok yox"),
            "definition": _(
                "available_spaces_qs: commercial VACANT, operational AVAILABLE, "
                "əlçatanlıq tarixi, aktiv/bağlayıcı icarə və rezervasiya yox."
            ),
        },
    ]

    from apps.residents.attendance import late_employees_for_day

    _late_rows, late_staff_count, _late_note, _late_roster = late_employees_for_day(
        day=today, roster="active"
    )
    late_staff_url = (
        f"{reverse('erp:internal_staff_access')}?date={today.isoformat()}&late=1"
    )

    # Secondary portfolio (expiring / AR / WO) — not the top building strip
    kpi_portfolio = [
        {
            "label": _("Bitən icarə (90g)"),
            "value": prop.get("leases_expiring_count"),
            "unit": "",
            "url": f"{reverse('erp:leases')}?filter=expiring",
            "meta": _("active/expiring · end_date"),
            "definition": "",
        },
        {
            "label": _("Gecikmiş debitor"),
            "value": float(fin.get("overdue_amount") or 0),
            "unit": fin.get("currency") or "AZN",
            "url": reverse("erp:ar_aging"),
            "meta": _(
                "%(n)s faktura · as-of %(d)s"
            )
            % {
                "n": fin.get("overdue_count") or 0,
                "d": as_of.strftime("%d.%m.%Y"),
            },
            "definition": _("due_date < as-of · bal > 0 (operational AR)"),
        },
        {
            "label": _("Açıq iş sifarişi"),
            "value": fm.get("open_wo"),
            "unit": "",
            "url": (
                f"{reverse('erp:reports_drill', kwargs={'section': 'fm'})}"
                f"?date_to={as_of.isoformat()}&date_from={as_of.isoformat()}"
            ),
            "meta": _("as-of %(d)s · eyni qayda") % {"d": as_of.strftime("%d.%m.%Y")},
            "definition": fm.get("rule", "") if isinstance(fm.get("rule"), str) else "",
        },
        {
            "label": _("Bu gün gecikənlər"),
            "value": late_staff_count,
            "unit": "",
            "url": late_staff_url,
            "meta": _("City Point · 09:00 · Asia/Baku"),
            "definition": _(
                "Yalnız daxili City Point işçiləri; binaya giriş oxuyucusu; "
                "ilk etibarlı giriş − 09:00."
            ),
        },
    ]

    # Upcoming events — visible window: next 30 calendar days (Asia/Baku localdate)
    events_horizon_days = 30
    horizon = today + timedelta(days=events_horizon_days)
    upcoming = []
    for lease in prop.get("leases_expiring") or []:
        if lease.end_date is None or lease.end_date < today or lease.end_date > horizon:
            continue
        upcoming.append(
            {
                "kind": _("İcarə bitməsi"),
                "title": getattr(lease, "code", str(lease)),
                "when": lease.end_date,
                "url": reverse("erp:lease_detail", kwargs={"code": lease.code}),
            }
        )
    from apps.crm.models import ActivityType

    viewing_qs = (
        LeadActivity.objects.filter(
            activity_type=ActivityType.VIEWING,
            occurred_at__date__gte=today,
            occurred_at__date__lte=horizon,
        )
        .select_related("lead", "opportunity")
        .order_by("occurred_at")[:12]
    )
    for act in viewing_qs:
        lead = act.lead
        title = (lead.company_name or lead.full_name) if lead else str(act)
        upcoming.append(
            {
                "kind": _("Sahə baxışı"),
                "title": title,
                "when": act.occurred_at.date() if act.occurred_at else today,
                "url": (
                    reverse("erp:crm_lead_detail", kwargs={"pk": lead.pk})
                    if lead
                    else reverse("erp:crm_leads")
                ),
            }
        )
    for plan in MaintenancePlan.objects.filter(
        is_active=True, next_due__isnull=False, next_due__gte=today, next_due__lte=horizon
    ).order_by("next_due")[:12]:
        upcoming.append(
            {
                "kind": _("Texniki plan"),
                "title": plan.name,
                "when": plan.next_due,
                "url": reverse("erp:maintenance_plans"),
            }
        )
    upcoming.sort(key=lambda r: r["when"] or today)
    upcoming = upcoming[:12]

    from apps.comms.links import user_notifications

    alerts_url = reverse("erp:alerts")
    recent_activity = []
    for n in user_notifications(user, namespace="erp", limit=10):
        recent_activity.append(
            {
                "title": n.message or n.event_key or _("Bildiriş"),
                "when": n.created_at,
                "url": getattr(n, "target_url", None) or alerts_url,
                "unread": not n.is_read,
            }
        )

    shortcuts = [
        {
            "label": _("İdarə hesabatları"),
            "url": reverse("erp:reports"),
            "icon": "bar-chart-3",
        },
        {
            "label": _("Excel eksport"),
            "url": reverse("erp:reports_export"),
            "icon": "download",
        },
        {
            "label": _("Bu gün gecikənlər"),
            "url": late_staff_url,
            "icon": "clock",
        },
        {
            "label": _("CP davamiyyət"),
            "url": reverse("erp:internal_staff_access"),
            "icon": "id-card",
        },
    ]

    modules = [
        {
            "key": "ops",
            "title": _("Bina əməliyyatları"),
            "subtitle": _("WO / ticket"),
            "icon": "wrench",
            "url": reverse("erp:work_orders"),
            "kpi": fm.get("open_wo"),
            "kpi_label": _("açıq WO"),
            "meta": "",
        },
        {
            "key": "finance",
            "title": _("Maliyyə təsdiqləri"),
            "subtitle": _("AR + AP · GL yox"),
            "icon": "calculator",
            "url": f"{pay_base}?queue=ar",
            "kpi": pending_payments + pending_ap_payments,
            "kpi_label": _("ödəniş"),
            "meta": "",
        },
    ]

    display_date = date_format(as_of, "j E Y")

    return {
        "is_management_hub": True,
        "is_sales_dashboard": False,
        "hub_modules": modules,
        "pending_offers": pending_offers,
        "pending_payments": pending_payments,
        "pending_ap_payments": pending_ap_payments,
        "pending_procurement": pending_procurement,
        "pending_documents": pending_documents,
        "pending_total": pending_total,
        "show_approvals": True,
        "people_inside_count": 0,
        "security_alerts": security_alerts,
        "decision_queue": decision_queue,
        "building_kpis": building_kpis,
        "kpi_portfolio": kpi_portfolio,
        "kpi_links": [
            {
                "label": _("Gözləyən təsdiq"),
                "value": pending_total,
                "url": approvals_url,
                "meta": "",
            },
            {
                "label": _("AR ödəniş"),
                "value": pending_payments,
                "url": f"{pay_base}?queue=ar",
                "meta": _("Debitor"),
            },
            {
                "label": _("AP ödəniş"),
                "value": pending_ap_payments,
                "url": f"{pay_base}?queue=ap",
                "meta": _("Kreditor"),
            },
        ],
        "upcoming_events": upcoming,
        "upcoming_events_period_label": _(
            "Növbəti %(n)s gün · Asia/Baku · %(start)s–%(end)s"
        )
        % {
            "n": events_horizon_days,
            "start": today.strftime("%d.%m.%Y"),
            "end": horizon.strftime("%d.%m.%Y"),
        },
        "upcoming_events_days": events_horizon_days,
        "recent_activity": recent_activity,
        "recent_activity_list_url": alerts_url,
        "mgmt_shortcuts": shortcuts,
        "report_as_of": as_of,
        "mgmt_display_date": display_date,
        "report_currency": "AZN",
        "occupancy_pct": occupancy_display,
        "occupancy_pct_label": _("Sahə üzrə doluluq (%)"),
        "active_leases": Lease.objects.filter(status=LeaseStatus.ACTIVE).count(),
        "property_rule": occupancy_rule,
        "inventory_types_note": inventory_types,
        "building_inventory": inventory,
    }


def is_management_user(user) -> bool:
    return getattr(user, "role", None) == Role.MANAGEMENT
