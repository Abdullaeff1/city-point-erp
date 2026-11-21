"""Department dashboard builders — real ORM aggregates only (Phase 3).

Shared shape returned by each builder:
  kpis, stats, pending, recent, notifications, quick_actions, reports
"""

from __future__ import annotations

from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.comms.models import Notification
from apps.rbac.services import user_has_permission


def _empty_board() -> dict:
    return {
        "kpis": [],
        "stats": [],
        "pending": [],
        "recent": [],
        "notifications": [],
        "quick_actions": [],
        "reports": [],
    }


def _kpi(label, value, *, url=None, meta=None) -> dict:
    item = {"label": label, "value": value}
    if url:
        item["url"] = url
    if meta:
        item["meta"] = meta
    return item


def _link(label, url_name, *, icon="arrow-right", mutate_perm=None, user=None) -> dict | None:
    if mutate_perm and user is not None and not user_has_permission(user, mutate_perm):
        return None
    return {"label": label, "url": reverse(url_name), "icon": icon}


def _user_notifications(user, limit=8) -> list[dict]:
    if not user or not getattr(user, "is_authenticated", False):
        return []
    rows = Notification.objects.filter(user=user).order_by("-created_at")[:limit]
    return [
        {
            "title": n.message or _("Bildiriş"),
            "at": n.created_at,
            "url": reverse("erp:alerts"),
            "unread": not n.is_read,
        }
        for n in rows
    ]


def build_facility_dashboard(user) -> dict:
    from apps.maintenance.access import work_orders_queryset_for
    from apps.maintenance.models import WorkOrderStatus
    from apps.property.models import CommercialStatus, Space
    from apps.tickets.access import tickets_visible_to
    from apps.tickets.models import OPEN_STATUSES

    board = _empty_board()
    spaces = Space.objects.all()
    vacant = spaces.filter(commercial_status=CommercialStatus.VACANT).count()
    occupied = spaces.filter(
        commercial_status__in=(
            CommercialStatus.ACTIVE,
            CommercialStatus.CONTRACTED,
            CommercialStatus.NOTICE,
        )
    ).count()
    reserved = spaces.filter(commercial_status=CommercialStatus.RESERVED).count()
    total = spaces.count()

    visible = tickets_visible_to(user)
    open_list = list(visible.filter(status__in=OPEN_STATUSES).select_related("company", "category")[:50])
    open_count = visible.filter(status__in=OPEN_STATUSES).count()
    sla_risk = sum(1 for t in open_list if getattr(t, "sla_risk", False))
    sla_breach = sum(1 for t in open_list if getattr(t, "sla_breached", False))
    unassigned = visible.filter(status__in=OPEN_STATUSES, assignee__isnull=True).count()

    open_wo_qs = work_orders_queryset_for(user).filter(
        status__in=(WorkOrderStatus.OPEN, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS)
    )
    open_wo_count = open_wo_qs.count()
    open_wo_list = list(open_wo_qs.select_related("ticket")[:8])

    board["kpis"] = [
        _kpi(_("Sahələr"), total, url=reverse("erp:spaces")),
        _kpi(_("Boş"), vacant, url=reverse("erp:spaces") + "?status=vacant"),
        _kpi(_("Məşğul"), occupied),
        _kpi(_("Açıq ticket"), open_count, url=reverse("erp:tickets")),
        _kpi(_("Açıq WO"), open_wo_count, url=reverse("erp:work_orders")),
        _kpi(_("SLA risk"), sla_risk + sla_breach, meta=_("pozuntu: %(n)s") % {"n": sla_breach}),
    ]
    board["stats"] = [
        {"label": _("Rezerv"), "value": reserved},
        {"label": _("Təyinatsız ticket"), "value": unassigned},
    ]
    board["pending"] = [
        {
            "title": wo.code,
            "meta": wo.ticket.code if wo.ticket_id else "",
            "url": reverse("erp:work_order_detail", kwargs={"code": wo.code}),
        }
        for wo in open_wo_list
    ] or [
        {
            "title": t.code,
            "meta": t.company.name if t.company_id else "",
            "url": reverse("erp:ticket_detail", kwargs={"code": t.code}),
        }
        for t in open_list[:8]
    ]
    board["recent"] = [
        {
            "title": f"{t.code} · {t.get_status_display()}",
            "at": t.updated_at,
            "url": reverse("erp:ticket_detail", kwargs={"code": t.code}),
        }
        for t in visible.order_by("-updated_at")[:8]
    ]
    board["notifications"] = _user_notifications(user)
    actions = [
        _link(_("Sahələr"), "erp:spaces", icon="building-2"),
        _link(_("Ticketlər"), "erp:tickets", icon="ticket"),
        _link(_("İş sifarişləri"), "erp:work_orders", icon="wrench"),
        _link(
            _("Yeni iş tapşırığı"),
            "erp:work_order_create",
            icon="plus",
            mutate_perm="work_order.create",
            user=user,
        ),
        _link(_("Avadanlıqlar"), "erp:building_equipment", icon="cpu"),
    ]
    board["quick_actions"] = [a for a in actions if a]
    board["reports"] = [
        {"label": _("SLA hesabat"), "url": reverse("erp:sla_report")},
    ]
    return board


def build_helpdesk_dashboard(user) -> dict:
    from apps.tickets.access import tickets_visible_to
    from apps.tickets.models import OPEN_STATUSES

    board = _empty_board()
    visible = tickets_visible_to(user)
    open_qs = visible.filter(status__in=OPEN_STATUSES)
    open_list = list(open_qs.select_related("company", "department", "category")[:80])
    open_count = open_qs.count()
    unassigned = open_qs.filter(assignee__isnull=True).count()
    sla_risk = sum(1 for t in open_list if getattr(t, "sla_risk", False))
    sla_breach = sum(1 for t in open_list if getattr(t, "sla_breached", False))

    by_dept: dict[str, int] = {}
    for t in open_list:
        name = t.department.name if t.department_id else _("Şöbəsiz")
        by_dept[name] = by_dept.get(name, 0) + 1

    board["kpis"] = [
        _kpi(_("Açıq"), open_count, url=reverse("erp:tickets")),
        _kpi(_("Təyinatsız"), unassigned, url=reverse("erp:tickets")),
        _kpi(_("SLA risk"), sla_risk),
        _kpi(_("SLA pozuntu"), sla_breach),
    ]
    board["stats"] = [{"label": k, "value": v} for k, v in sorted(by_dept.items(), key=lambda x: -x[1])[:6]]
    board["pending"] = [
        {
            "title": t.code,
            "meta": t.get_status_display(),
            "url": reverse("erp:ticket_detail", kwargs={"code": t.code}),
        }
        for t in open_list[:10]
    ]
    board["recent"] = [
        {
            "title": f"{t.code} · {t.get_status_display()}",
            "at": t.updated_at,
            "url": reverse("erp:ticket_detail", kwargs={"code": t.code}),
        }
        for t in visible.order_by("-updated_at")[:10]
    ]
    board["notifications"] = _user_notifications(user)
    create = _link(_("Yeni ticket"), "erp:ticket_create", icon="plus", mutate_perm="ticket.create", user=user)
    actions = [
        create,
        _link(_("Ticketlər"), "erp:tickets", icon="ticket"),
        _link(_("İş sifarişləri"), "erp:work_orders", icon="wrench"),
        _link(_("SLA"), "erp:sla_report", icon="timer"),
    ]
    board["quick_actions"] = [a for a in actions if a]
    board["reports"] = [{"label": _("SLA hesabat"), "url": reverse("erp:sla_report")}]
    return board


def build_hr_dashboard(user) -> dict:
    from apps.reception.models import GuestVisit, VisitStatus
    from apps.residents.access import currently_inside_employee_rows
    from apps.residents.models import ResidentCompany, ResidentEmployee

    board = _empty_board()
    today = timezone.localdate()
    cp = ResidentCompany.objects.filter(slug="city-point").first()
    internal = (
        ResidentEmployee.objects.filter(company=cp, is_active=True) if cp else ResidentEmployee.objects.none()
    )
    internal_count = internal.count()
    former_count = (
        ResidentEmployee.objects.filter(company=cp, is_active=False).count() if cp else 0
    )
    employees_inside = currently_inside_employee_rows(today)
    # HR roster is city-point only — keep "inside" KPI aligned with that list.
    cp_inside = [
        row
        for row in employees_inside
        if getattr(row.get("company"), "slug", None) == "city-point"
    ]
    guests_inside = GuestVisit.objects.filter(scheduled_for=today, status=VisitStatus.INSIDE).count()

    board["kpis"] = [
        _kpi(_("Daxili işçilər"), internal_count, url=reverse("erp:internal_staff_access")),
        _kpi(
            _("CP içəridə"),
            len(cp_inside),
            url=reverse("erp:internal_staff_access") + f"?date={today.isoformat()}",
        ),
        _kpi(
            _("Keçmiş işçilər"),
            former_count,
            url=reverse("erp:internal_staff_access") + "?roster=former",
        ),
        _kpi(_("Qonaq içəridə"), guests_inside, url=reverse("erp:people_inside")),
    ]
    board["stats"] = [
        {"label": _("Aktiv əməkdaş (CP)"), "value": internal_count},
        {"label": _("Rejim"), "value": _("Baxış / export")},
    ]
    board["pending"] = []
    board["recent"] = []
    for row in cp_inside[:8]:
        emp = row.get("employee")
        url = reverse("erp:people_inside")
        if emp is not None and getattr(emp, "pk", None):
            url = reverse("erp:internal_staff_access_detail", kwargs={"pk": emp.pk})
        board["recent"].append(
            {
                "title": row.get("name") or getattr(emp, "full_name", None) or _("İşçi"),
                "meta": getattr(row.get("company"), "name", "") or "",
                "url": url,
            }
        )
    board["notifications"] = _user_notifications(user)
    actions = [
        _link(_("CP işçilər"), "erp:internal_staff_access", icon="id-card"),
        _link(_("İçəridə (ümumi)"), "erp:people_inside", icon="users"),
    ]
    board["quick_actions"] = [a for a in actions if a]
    board["reports"] = []
    if user_has_permission(user, "residents.export_access"):
        board["reports"].append(
            {
                "label": _("Davamiyyət Excel"),
                "url": reverse("erp:internal_staff_access_export") + "?range=month",
            }
        )
    return board


def build_procurement_dashboard(user) -> dict:
    from apps.procurement.models import POStatus, PurchaseOrder, PurchaseRequest, PRStatus
    from apps.warehouse.models import Stock

    board = _empty_board()
    open_prs = PurchaseRequest.objects.exclude(status=PRStatus.REJECTED)
    pending_prs = PurchaseRequest.objects.filter(
        status__in=(PRStatus.SUBMITTED, PRStatus.DRAFT)
    ).count()
    po_open = PurchaseOrder.objects.exclude(
        status__in=(POStatus.RECEIVED, POStatus.CLOSED, POStatus.CANCELLED)
    ).count()

    low_stock = (
        Stock.objects.select_related("sku")
        .filter(sku__reorder_level__gt=0)
        .filter(quantity__lte=F("sku__reorder_level"))
        .count()
    )
    stock_rows = Stock.objects.count()

    board["kpis"] = [
        _kpi(_("Açıq PR"), open_prs.count(), url=reverse("erp:procurement")),
        _kpi(_("Açıq PO"), po_open, url=reverse("erp:procurement")),
        _kpi(_("Aşağı stok"), low_stock, url=reverse("erp:warehouse") + "?low=1"),
        _kpi(_("Stok sətirləri"), stock_rows, url=reverse("erp:warehouse")),
    ]
    board["stats"] = [{"label": _("Gözləyən PR"), "value": pending_prs}]
    board["pending"] = [
        {
            "title": pr.code,
            "meta": pr.get_status_display(),
            "url": reverse("erp:procurement"),
        }
        for pr in open_prs.order_by("-id")[:8]
    ]
    board["recent"] = board["pending"][:5]
    board["notifications"] = _user_notifications(user)
    edit = user_has_permission(user, "procurement.edit")
    actions = [
        _link(_("Satınalma"), "erp:procurement", icon="shopping-cart"),
        _link(
            _("Yeni PR"),
            "erp:procurement_pr_create",
            icon="plus",
            mutate_perm="procurement.edit",
            user=user,
        ),
        _link(_("Təchizatçılar"), "erp:procurement_suppliers", icon="building"),
        _link(_("Anbar"), "erp:warehouse", icon="warehouse"),
    ]
    board["quick_actions"] = [a for a in actions if a]
    if not edit:
        board["stats"].append({"label": _("Rejim"), "value": _("Baxış")})
    board["reports"] = []
    return board


def build_it_dashboard(user, request=None) -> dict:
    from apps.audit.models import AuditLog
    from apps.erp.it_access import can_access_erp_audit, staff_users_queryset

    board = _empty_board()
    axtrax = None
    try:
        from apps.integrations.axtrax_health import axtrax_sync_health

        axtrax = axtrax_sync_health()
    except Exception:
        axtrax = None

    staff_qs = staff_users_queryset()
    staff_count = staff_qs.filter(is_active=True).count()
    inactive_count = staff_qs.filter(is_active=False).count()
    can_audit = can_access_erp_audit(user, request)
    can_users = user_has_permission(user, "user.view") or user_has_permission(user, "user.admin")
    users_url = reverse("erp:staff_users") if can_users else None

    board["kpis"] = [
        _kpi(_("Aktiv istifadəçi"), staff_count, url=users_url),
        _kpi(_("Deaktiv"), inactive_count, url=(users_url + "?status=inactive") if users_url else None),
    ]
    if can_audit:
        board["kpis"].append(
            _kpi(_("Audit qeyd"), AuditLog.objects.count(), url=reverse("erp:audit"))
        )
    if axtrax:
        ok = axtrax.get("events_ok")
        board["kpis"].append(
            _kpi(
                _("AxTrax events"),
                _("OK") if ok else _("Stale / yox"),
                meta=_("oxu sync — yazma yoxdur"),
            )
        )
        board["stats"].append(
            {
                "label": _("AxTrax"),
                "value": _("OK") if ok else _("Yoxlanılmalıdır"),
            }
        )
    board["pending"] = []
    if can_audit:
        recent_logs = list(AuditLog.objects.order_by("-created_at")[:10])
        board["recent"] = [
            {
                "title": getattr(log, "action", None) or getattr(log, "verb", None) or str(log.pk),
                "meta": str(getattr(log, "actor", "") or "")[:60],
                "at": getattr(log, "created_at", None),
                "url": reverse("erp:audit"),
            }
            for log in recent_logs
        ]
    elif can_users:
        board["recent"] = [
            {
                "title": u.display_name,
                "meta": u.get_role_display(),
                "url": reverse("erp:staff_user_detail", kwargs={"pk": u.pk}),
            }
            for u in staff_qs.filter(is_active=True)[:8]
        ]
    board["notifications"] = _user_notifications(user)
    actions = []
    if can_users:
        actions.append(_link(_("İstifadəçilər"), "erp:staff_users", icon="users"))
    if can_audit:
        actions.append(_link(_("Audit"), "erp:audit", icon="scroll-text"))
    if user_has_permission(user, "user.admin"):
        actions.append({"label": _("Django Admin"), "url": "/admin/accounts/user/", "icon": "shield"})
    if user_has_permission(user, "report.view"):
        actions.append(_link(_("Hesabatlar"), "erp:reports", icon="bar-chart-3"))
    actions.append(_link(_("Ops panel"), "erp:dashboard", icon="layout-dashboard"))
    # Ops dashboard uses ?ops=1 for Admin landing override.
    for a in actions:
        if a and a.get("url") == reverse("erp:dashboard") and getattr(user, "role", None) == "admin":
            a["url"] = reverse("erp:dashboard") + "?ops=1"
    board["quick_actions"] = [a for a in actions if a]
    board["reports"] = []
    if user_has_permission(user, "report.view"):
        board["reports"].append({"label": _("İcra hesabatları"), "url": reverse("erp:reports")})
    if user_has_permission(user, "user.admin"):
        board["reports"].append({"label": _("Admin — istifadəçilər"), "url": "/admin/accounts/user/"})
    return board


def enhance_management_hub(hub: dict, user) -> dict:
    """Attach shared pending/notifications/quick_actions onto management hub context."""
    hub = dict(hub)
    hub.setdefault("notifications", _user_notifications(user))
    actions = [
        _link(_("Təsdiqlər"), "erp:approvals", icon="check-circle"),
        _link(_("Hesabatlar"), "erp:reports", icon="bar-chart-3"),
        _link(_("Rezidentlər"), "erp:residents", icon="building"),
    ]
    if user_has_permission(user, "announcement.publish") or getattr(user, "role", None) == "management":
        actions.append(_link(_("Elanlar"), "erp:announcements", icon="megaphone"))
    hub["quick_actions"] = [a for a in actions if a]
    return hub
