"""Rəhbərlik (Management) ERP yan menyu — yalnız icazəli, real marşrutlar."""

from __future__ import annotations

from django.urls import reverse
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.accounts.nav import build_nav_flags


def _item(
    *,
    label: str,
    url: str,
    icon: str = "",
    match: tuple[str, ...] = (),
    match_query: dict | None = None,
    badge_key: str = "",
) -> dict:
    return {
        "label": label,
        "url": url,
        "icon": icon,
        "match": match,
        "match_query": match_query or {},
        "badge_key": badge_key,
        "is_active": False,
    }


def _q_active(item: dict, *, url_name: str | None, query) -> bool:
    if not url_name or url_name not in item["match"]:
        return False
    mq = item.get("match_query") or {}
    if not mq:
        return True
    for key, want in mq.items():
        got = (query.get(key) or "").strip()
        if want:
            if got != want:
                return False
        else:
            # Empty want = only active when that query key is unset / blank
            if got:
                return False
    return True


def build_management_nav(user, *, url_name: str | None = None, query=None) -> list[dict]:
    """Permission-filtered collapsible nav groups for Role.MANAGEMENT."""
    if not user or getattr(user, "role", None) != Role.MANAGEMENT:
        return []

    flags = build_nav_flags(user)
    query = query or {}

    groups: list[dict] = []

    # —— İdarə paneli: birbaşa link (içində «Ümumi baxış» yoxdur) ——
    groups.append(
        {
            "key": "dashboard",
            "kind": "link",
            "label": _("İdarə paneli"),
            "icon": "layout-dashboard",
            "url": reverse("erp:dashboard"),
            "match": ("dashboard",),
            "items": [],
        }
    )

    # —— Əmlak və icarə ——
    property_items: list[dict] = []
    if flags.get("nav_property"):
        property_items.extend(
            [
                _item(
                    label=_("Obyekt paneli"),
                    url=reverse("erp:supply_dashboard"),
                    icon="layout-grid",
                    match=("supply_dashboard", "facility_dashboard", "helpdesk_dashboard"),
                ),
                _item(
                    label=_("Sahələr"),
                    url=reverse("erp:spaces"),
                    icon="building-2",
                    match=("spaces", "space_detail", "space_edit", "space_create", "floor_create"),
                    match_query={"status": ""},
                ),
                _item(
                    label=_("Boş sahələr"),
                    url=f"{reverse('erp:spaces')}?status=vacant",
                    icon="door-open",
                    match=("spaces",),
                    match_query={"status": "vacant"},
                ),
                _item(
                    label=_("Dolu sahələr"),
                    url=f"{reverse('erp:spaces')}?status=occupied",
                    icon="key-round",
                    match=("spaces",),
                    match_query={"status": "occupied"},
                ),
            ]
        )
    if flags.get("nav_building_assets"):
        property_items.extend(
            [
                _item(
                    label=_("Avadanlıqlar"),
                    url=reverse("erp:building_equipment"),
                    icon="cpu",
                    match=("building_equipment", "building_assets"),
                ),
                _item(
                    label=_("İnventarlar"),
                    url=reverse("erp:building_inventory"),
                    icon="boxes",
                    match=("building_inventory",),
                ),
            ]
        )
    if flags.get("nav_residents"):
        property_items.append(
            _item(
                label=_("Rezident şirkətlər"),
                url=reverse("erp:residents"),
                icon="building",
                match=(
                    "residents",
                    "resident_detail",
                    "resident_documents",
                    "resident_employees",
                    "resident_employee_access",
                    "resident_tickets",
                    "resident_guests",
                    "resident_create",
                    "resident_edit",
                ),
                badge_key="residents",
            )
        )
    if flags.get("nav_leases"):
        property_items.extend(
            [
                _item(
                    label=_("İcarələr"),
                    url=reverse("erp:leases"),
                    icon="file-signature",
                    match=("leases", "lease_detail"),
                    match_query={"filter": ""},
                ),
                _item(
                    label=_("Bitən icarələr (90g)"),
                    url=f"{reverse('erp:leases')}?filter=expiring",
                    icon="calendar-clock",
                    match=("leases",),
                    match_query={"filter": "expiring"},
                ),
            ]
        )
    if property_items:
        groups.append(
            {
                "key": "property",
                "label": _("Əmlak və icarə"),
                "icon": "building-2",
                "items": property_items,
            }
        )

    # —— Kommersiya ——
    if flags.get("nav_crm"):
        groups.append(
            {
                "key": "commercial",
                "label": _("Kommersiya"),
                "icon": "handshake",
                "items": [
                    _item(
                        label=_("Lidlər"),
                        url=reverse("erp:crm_leads"),
                        icon="user-plus",
                        match=("crm_leads", "crm_lead_detail"),
                    ),
                    _item(
                        label=_("İmkanlar"),
                        url=reverse("erp:crm_opportunities"),
                        icon="target",
                        match=("crm_opportunities", "crm_opportunity_detail"),
                    ),
                    _item(
                        label=_("Təkliflər"),
                        url=reverse("erp:crm_offers"),
                        icon="handshake",
                        match=("crm_offers", "crm_offer_detail"),
                    ),
                    _item(
                        label=_("İcarə müraciətləri"),
                        url=reverse("erp:crm_lease_applications"),
                        icon="file-plus",
                        match=("crm_lease_applications", "crm_lease_application_detail"),
                    ),
                    _item(
                        label=_("Əlçatan sahələr"),
                        url=reverse("erp:crm_available_spaces"),
                        icon="door-open",
                        match=("crm_available_spaces", "crm_space_detail"),
                    ),
                    # Shortcut only — primary active state lives under Hesabatlar
                    _item(
                        label=_("CRM hesabat"),
                        url=reverse("erp:crm_reports"),
                        icon="pie-chart",
                        match=(),
                    ),
                ],
            }
        )

    # —— Bina əməliyyatları ——
    ops_items: list[dict] = []
    if flags.get("nav_tickets"):
        ops_items.extend(
            [
                _item(
                    label=_("Təchizat şöbəsi"),
                    url=reverse("erp:supply_dashboard"),
                    icon="headset",
                    match=("supply_dashboard", "helpdesk_dashboard", "facility_dashboard"),
                ),
                _item(
                    label=_("Ticketlər"),
                    url=reverse("erp:tickets"),
                    icon="ticket",
                    match=("tickets", "ticket_detail", "ticket_create"),
                ),
                _item(
                    label=_("SLA hesabatı"),
                    url=reverse("erp:sla_report"),
                    icon="timer",
                    match=("sla_report",),
                ),
            ]
        )
    if flags.get("nav_work_orders"):
        ops_items.extend(
            [
                _item(
                    label=_("İş sifarişləri"),
                    url=reverse("erp:work_orders"),
                    icon="wrench",
                    match=(
                        "work_orders",
                        "work_order_detail",
                        "work_order_create",
                        "work_order_import",
                    ),
                ),
                _item(
                    label=_("Texniki planlar"),
                    url=reverse("erp:maintenance_plans"),
                    icon="calendar-check",
                    match=("maintenance_plans", "maintenance_plan_create", "maintenance_plan_edit"),
                ),
            ]
        )
    ops_items.append(
        _item(
            label=_("İçəridə / təhlükəsizlik"),
            url=reverse("erp:people_inside"),
            icon="shield-check",
            match=("people_inside", "people_inside_detail", "people_inside_export"),
            badge_key="security",
        )
    )
    if flags.get("nav_internal_access"):
        ops_items.append(
            _item(
                label=_("CP işçilər"),
                url=reverse("erp:hr_dashboard"),
                icon="id-card",
                match=("hr_dashboard", "internal_staff_access", "internal_staff_access_detail"),
            )
        )
    if ops_items:
        groups.append(
            {
                "key": "operations",
                "label": _("Bina əməliyyatları"),
                "icon": "activity",
                "items": ops_items,
            }
        )

    # —— Anbar və satınalma ——
    if flags.get("nav_supply"):
        groups.append(
            {
                "key": "supply",
                "label": _("Anbar və satınalma"),
                "icon": "package",
                "items": [
                    _item(
                        label=_("Anbar"),
                        url=reverse("erp:warehouse"),
                        icon="warehouse",
                        match=(
                            "warehouse",
                            "warehouse_sku_detail",
                            "warehouse_sku_create",
                            "stocktake_list",
                            "stocktake_detail",
                        ),
                    ),
                    _item(
                        label=_("Satınalma"),
                        url=reverse("erp:procurement_dashboard"),
                        icon="shopping-cart",
                        match=(
                            "procurement",
                            "procurement_dashboard",
                            "procurement_pr_create",
                            "procurement_pr_detail",
                            "procurement_po_detail",
                            "procurement_rfq_detail",
                        ),
                    ),
                    _item(
                        label=_("Podratçılar"),
                        url=reverse("erp:procurement_suppliers"),
                        icon="truck",
                        match=(
                            "procurement_suppliers",
                            "procurement_supplier_detail",
                            "procurement_supplier_create",
                            "procurement_supplier_edit",
                        ),
                    ),
                ],
            }
        )

    # —— Sənədlər və kommunikasiya ——
    docs_items: list[dict] = []
    if flags.get("nav_docs"):
        docs_items.extend(
            [
                _item(
                    label=_("Sənədlər"),
                    url=reverse("erp:documents"),
                    icon="file-text",
                    match=("documents",),
                ),
                _item(
                    label=_("Kargüzarlıq"),
                    url=reverse("erp:correspondence_list"),
                    icon="mail",
                    match=("correspondence_list", "correspondence_detail"),
                ),
                _item(
                    label=_("Daxili prosedurlar"),
                    url=reverse("erp:building_procedures"),
                    icon="book-open",
                    match=("building_procedures", "building_procedure_create", "building_procedure_edit"),
                ),
            ]
        )
    docs_items.append(
        _item(
            label=_("Bildirişlər"),
            url=reverse("erp:alerts"),
            icon="bell",
            match=("alerts",),
            badge_key="alerts",
        )
    )
    if flags.get("nav_announcements"):
        docs_items.append(
            _item(
                label=_("Elanlar"),
                url=reverse("erp:announcements"),
                icon="megaphone",
                match=("announcements", "announcement_create", "announcement_edit"),
            )
        )
    if docs_items:
        groups.append(
            {
                "key": "docs_comms",
                "label": _("Sənədlər və kommunikasiya"),
                "icon": "file-text",
                "items": docs_items,
            }
        )

    # —— Maliyyə və təsdiqlər ——
    finance_items: list[dict] = []
    if flags.get("nav_approvals"):
        finance_items.extend(
            [
                _item(
                    label=_("Təsdiq növbəsi"),
                    url=reverse("erp:approvals"),
                    icon="check-circle",
                    match=("approvals",),
                    match_query={"workflow": ""},
                ),
                _item(
                    label=_("Debitor ödəniş (AR)"),
                    url=f"{reverse('erp:payment_approvals')}?queue=ar",
                    icon="banknote",
                    match=("payment_approvals",),
                    match_query={"queue": "ar"},
                ),
                _item(
                    label=_("Kreditor ödəniş (AP)"),
                    url=f"{reverse('erp:payment_approvals')}?queue=ap",
                    icon="wallet",
                    match=("payment_approvals",),
                    match_query={"queue": "ap"},
                ),
            ]
        )
    if flags.get("nav_finance"):
        finance_items.extend(
            [
                _item(
                    label=_("Debitor aging"),
                    url=reverse("erp:ar_aging"),
                    icon="clock",
                    match=("ar_aging",),
                ),
                _item(
                    label=_("Mühasibat dövrləri"),
                    url=reverse("erp:accounting_periods"),
                    icon="calendar-range",
                    match=("accounting_periods",),
                ),
                _item(
                    label=_("Billing (baxış)"),
                    url=reverse("erp:billing"),
                    icon="receipt",
                    match=("billing",),
                ),
            ]
        )
    if finance_items:
        groups.append(
            {
                "key": "finance",
                "label": _("Maliyyə və təsdiqlər"),
                "icon": "calculator",
                "items": finance_items,
            }
        )

    # —— Hesabatlar ——
    report_items: list[dict] = []
    if flags.get("nav_reports"):
        report_items.append(
            _item(
                label=_("İdarə hesabatları"),
                url=reverse("erp:reports"),
                icon="bar-chart-3",
                match=("reports", "reports_drill", "reports_export"),
            )
        )
    if flags.get("nav_crm"):
        report_items.append(
            _item(
                label=_("CRM hesabat / eksport"),
                url=reverse("erp:crm_reports"),
                icon="download",
                match=("crm_reports", "crm_reports_export"),
            )
        )
    if report_items:
        groups.append(
            {
                "key": "reports",
                "label": _("Hesabatlar"),
                "icon": "bar-chart-3",
                "items": report_items,
            }
        )

    for group in groups:
        if group.get("kind") == "link":
            active = bool(url_name) and url_name in (group.get("match") or ())
            group["is_active"] = active
            group["is_open"] = False
            continue

        group_active = False
        for item in group["items"]:
            active = _q_active(item, url_name=url_name, query=query)
            # payment_approvals without queue: treat as AR default for "ar" item only when queue blank
            if (
                url_name == "payment_approvals"
                and not (query.get("queue") or "").strip()
                and item.get("match_query", {}).get("queue") == "ar"
            ):
                active = True
            item["is_active"] = active
            if active:
                group_active = True
        group["is_open"] = group_active
        group["is_active"] = group_active

    return [g for g in groups if g.get("kind") == "link" or g["items"]]
