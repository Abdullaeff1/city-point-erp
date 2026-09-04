from apps.accounts.models import Role
from apps.comms.models import Notification


def role_context(request):
    user = getattr(request, "user", None)
    unread = 0
    if user and user.is_authenticated:
        unread = Notification.objects.filter(user=user, is_read=False).count()
    role = getattr(user, "role", None) if user and user.is_authenticated else None
    is_adminish = role in {Role.ADMIN, Role.MANAGEMENT}
    return {
        "unread_alerts": unread,
        "nav_reception": is_adminish or role == Role.RECEPTION,
        "nav_tickets": is_adminish or role in {Role.SERVICE_DESK, Role.PROPERTY_FM},
        "nav_property": is_adminish or role == Role.PROPERTY_FM,
        "nav_residents": is_adminish or role in {Role.SERVICE_DESK, Role.PROPERTY_FM, Role.RECEPTION},
        "nav_docs": True,
        "nav_reports": is_adminish,
    }
