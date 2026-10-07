"""Admin role preview: switch session to a staff demo user and restore later."""

from __future__ import annotations

from django.contrib.auth import get_user_model, login

from apps.accounts.models import Role

SESSION_IMPERSONATOR_ID = "cp_impersonator_id"

# Preferred seeded accounts for one-click role preview.
ROLE_SWITCH_TARGETS: list[tuple[str, str]] = [
    (Role.ADMIN, "admin@citypoint.az"),
    (Role.MANAGEMENT, "manager@citypoint.az"),
    (Role.RECEPTION, "reception@citypoint.az"),
    (Role.SERVICE_DESK, "desk@citypoint.az"),
    (Role.PROPERTY_FM, "fm@citypoint.az"),
    (Role.SECURITY, "security@citypoint.az"),
]


def can_start_impersonation(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or getattr(user, "role", None) == Role.ADMIN)


def get_impersonator(request):
    raw = request.session.get(SESSION_IMPERSONATOR_ID)
    if not raw:
        return None
    User = get_user_model()
    try:
        return User.objects.get(pk=raw, is_active=True)
    except User.DoesNotExist:
        request.session.pop(SESSION_IMPERSONATOR_ID, None)
        return None


def is_impersonating(request) -> bool:
    return get_impersonator(request) is not None


def resolve_role_user(role: str):
    """Return preferred seeded user for role, else any active user with that role."""
    User = get_user_model()
    preferred = dict(ROLE_SWITCH_TARGETS).get(role)
    if preferred:
        user = User.objects.filter(email__iexact=preferred, is_active=True).first()
        if user:
            return user
    return User.objects.filter(role=role, is_active=True).order_by("id").first()


def list_role_switch_targets(request) -> list[dict]:
    current_id = request.user.pk if request.user.is_authenticated else None
    items = []
    for role, _email in ROLE_SWITCH_TARGETS:
        user = resolve_role_user(role)
        if not user:
            continue
        items.append(
            {
                "role": role,
                "label": user.get_role_display(),
                "email": user.email,
                "user_id": user.pk,
                "is_current": user.pk == current_id,
            }
        )
    return items


def start_impersonation(request, target) -> None:
    """Log in as target; remember original admin once across role hops."""
    if SESSION_IMPERSONATOR_ID in request.session:
        impersonator_id = request.session[SESSION_IMPERSONATOR_ID]
    else:
        if not can_start_impersonation(request.user):
            raise PermissionError("Only admin can switch roles")
        if target.pk == request.user.pk:
            raise PermissionError("Already this user")
        impersonator_id = request.user.pk

    login(request, target, backend="django.contrib.auth.backends.ModelBackend")
    request.session[SESSION_IMPERSONATOR_ID] = impersonator_id
    request.session.modified = True


def stop_impersonation(request):
    """Restore original admin session. Returns admin user or None."""
    impersonator = get_impersonator(request)
    if not impersonator:
        return None
    request.session.pop(SESSION_IMPERSONATOR_ID, None)
    login(request, impersonator, backend="django.contrib.auth.backends.ModelBackend")
    request.session.pop(SESSION_IMPERSONATOR_ID, None)
    request.session.modified = True
    return impersonator


def actor_can_switch_roles(request) -> bool:
    """True if current user is admin, or session is an admin preview."""
    if is_impersonating(request):
        return can_start_impersonation(get_impersonator(request))
    return can_start_impersonation(request.user)
