from apps.accounts.impersonation import (
    actor_can_switch_roles,
    can_start_impersonation,
    get_impersonator,
    is_impersonating,
    list_role_switch_targets,
)
from apps.accounts.models import Role
from apps.accounts.portal_scope import MODE_ALL, get_portal_scope
from apps.comms.models import Notification


def role_context(request):
    user = getattr(request, "user", None)
    unread = 0
    open_rapid_alerts = 0
    open_shaft_alerts = 0
    resident_count = 0
    if user and user.is_authenticated:
        unread = Notification.objects.filter(user=user, is_read=False).count()
        if getattr(user, "can_access_security_portal", lambda: False)():
            from apps.residents.models import RapidCardSwipeAlert, ShaftAccessAlert

            open_rapid_alerts = RapidCardSwipeAlert.objects.filter(acknowledged_at__isnull=True).count()
            open_shaft_alerts = ShaftAccessAlert.objects.filter(acknowledged_at__isnull=True).count()
    role = getattr(user, "role", None) if user and user.is_authenticated else None
    is_adminish = role in {Role.ADMIN, Role.MANAGEMENT}
    nav_residents = is_adminish or role in {Role.SERVICE_DESK, Role.PROPERTY_FM, Role.RECEPTION}
    if user and user.is_authenticated and nav_residents:
        from apps.residents.models import ResidentCompany

        resident_count = ResidentCompany.objects.filter(is_internal=False).count()

    can_switch = False
    role_targets = []
    impersonator = None
    impersonating = False
    if user and user.is_authenticated:
        can_switch = actor_can_switch_roles(request)
        if can_switch:
            role_targets = list_role_switch_targets(request)
        impersonating = is_impersonating(request)
        impersonator = get_impersonator(request) if impersonating else None

    portal_scope_label = ""
    portal_scope_mode = None
    portal_can_switch_company = False
    if user and user.is_authenticated and role == Role.RESIDENT_USER:
        scope = get_portal_scope(request)
        if scope:
            portal_scope_mode = scope.mode
            if scope.mode == MODE_ALL:
                portal_scope_label = f"Bütün şirkətlər ({len(scope.company_ids)})"
            elif scope.company_ids:
                from apps.residents.models import ResidentCompany

                company = ResidentCompany.objects.filter(pk=scope.company_ids[0]).first()
                portal_scope_label = company.name if company else ""
            from apps.accounts.portal_scope import eligible_company_ids_for

            portal_can_switch_company = len(eligible_company_ids_for(user)) > 1

    return {
        "unread_alerts": unread,
        "open_rapid_alerts": open_rapid_alerts,
        "open_shaft_alerts": open_shaft_alerts,
        "open_security_alerts": open_rapid_alerts + open_shaft_alerts,
        "resident_count": resident_count,
        "nav_reception": is_adminish or role == Role.RECEPTION,
        "nav_tickets": is_adminish or role in {Role.SERVICE_DESK, Role.PROPERTY_FM},
        "nav_property": is_adminish or role == Role.PROPERTY_FM,
        "nav_residents": nav_residents,
        "nav_docs": is_adminish,
        "nav_reports": is_adminish,
        "nav_internal_access": is_adminish,
        "nav_leases": is_adminish or role == Role.PROPERTY_FM,
        "nav_crm": is_adminish,
        "nav_supply": is_adminish,
        "nav_finance": is_adminish,
        "nav_audit": bool(
            user
            and user.is_authenticated
            and (
                role == Role.ADMIN
                or (impersonator and can_start_impersonation(impersonator))
            )
        ),
        "nav_role_switch": can_switch,
        "role_switch_targets": role_targets,
        "is_impersonating": impersonating,
        "impersonator": impersonator,
        "portal_scope_label": portal_scope_label,
        "portal_scope_mode": portal_scope_mode,
        "portal_can_switch_company": portal_can_switch_company,
    }
