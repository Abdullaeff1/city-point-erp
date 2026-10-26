"""Turn stored audit rows into role sections for the admin page."""

from django.utils.translation import gettext as _

from apps.accounts.models import Role

ROLE_ORDER = (
    Role.RECEPTION,
    Role.SERVICE_DESK,
    Role.SECURITY,
    Role.PROPERTY_FM,
    Role.MANAGEMENT,
    Role.ADMIN,
)

# Domain bus writes a second row for the same visit. Keep the reception row,
# which names the staff member who did the work.
DOMAIN_DUPLICATES = {
    "VisitorCheckedIn": "visit.check_in",
    "VisitorCheckedOut": "visit.check_out",
}


def action_label(action: str) -> str:
    labels = {
        "visit.check_in": _("Qəbul etdi"),
        "visit.check_out": _("Çıxış etdirdi"),
        "visit.updated": _("Qonağı dəyişdi"),
        "visit.cancelled": _("Ləğv etdi"),
        "visit.no_show": _("Gəlmədi"),
        "visit.return_pending": _("Vəsiqə gözlənilir"),
        "guest.created": _("Qonaq yaratdı"),
        "guest.updated": _("Qonaq məlumatını yenilədi"),
        "TicketCreated": _("Ticket yaratdı"),
        "TicketAssigned": _("Ticket təyin etdi"),
        "TicketResolved": _("Ticket həll etdi"),
        "VisitorCheckedIn": _("Qəbul etdi"),
        "VisitorCheckedOut": _("Çıxış etdirdi"),
        "lease.activated": _("İcarəni aktivləşdirdi"),
        "LeaseActivated": _("İcarəni aktivləşdirdi"),
        "LeaseTerminated": _("İcarəni dayandırdı"),
        "ApprovalRequested": _("Təsdiq istədi"),
        "ApprovalDecided": _("Təsdiq qərarı verdi"),
    }
    return labels.get(action, action)


def object_label(log) -> str:
    payload = log.new_values or {}
    guest = payload.get("guest")
    company = payload.get("company")
    if guest and company:
        return f"{guest} · {company}"
    if guest:
        return str(guest)
    return log.object_repr or "—"


def visible_logs(logs):
    """Drop domain-event twins of a reception check-in or check-out."""
    reception_visits = {
        (log.entity_type_id, log.entity_id, log.action)
        for log in logs
        if log.source == "reception" and log.entity_id and log.action in DOMAIN_DUPLICATES.values()
    }
    visible = []
    for log in logs:
        paired = DOMAIN_DUPLICATES.get(log.action)
        if (
            paired
            and log.source == "domain_event"
            and (log.entity_type_id, log.entity_id, paired) in reception_visits
        ):
            continue
        visible.append(log)
    return visible


def _role_label(role: str) -> str:
    try:
        return str(Role(role).label)
    except ValueError:
        return role or _("Digər")


def role_choices():
    return [(role, _role_label(role)) for role in ROLE_ORDER]


def audit_rows(logs):
    """One timeline. Caller already limited and, when asked, filtered by role."""
    rows = []
    for log in visible_logs(logs):
        role = getattr(log.actor, "role", None) or ""
        actor = log.actor
        rows.append(
            {
                "at": log.created_at,
                "role": role,
                "role_label": _role_label(role) if role else _("Digər"),
                "actor": actor.display_name if actor else "—",
                "email": actor.email if actor else "",
                "action": action_label(log.action),
                "object": object_label(log),
            }
        )
    rows.sort(key=lambda row: row["at"], reverse=True)
    return rows
