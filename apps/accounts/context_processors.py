from apps.accounts.models import Role
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
        "nav_parties": is_adminish or role in {Role.SERVICE_DESK, Role.PROPERTY_FM, Role.RECEPTION},
        "nav_docs": True,
        "nav_reports": is_adminish,
        "nav_internal_access": is_adminish,
        "nav_leases": is_adminish or role == Role.PROPERTY_FM,
        "nav_crm": is_adminish,
        "nav_fm": is_adminish or role in {Role.PROPERTY_FM, Role.SERVICE_DESK},
        "nav_supply": is_adminish,
        "nav_finance": is_adminish,
    }
