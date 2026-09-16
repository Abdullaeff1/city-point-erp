from django import template

from apps.reception.models import mask_fin

register = template.Library()

STATUS_CLASS = {
    "sent": "badge-sent",
    "accepted": "badge-accepted",
    "in_progress": "badge-progress",
    "resolved": "badge-resolved",
    "waiting": "badge-sent",
    "pre_registered": "badge-sent",
    "inside": "badge-progress",
    "left": "badge-muted",
    "cancelled": "badge-muted",
    "no_show": "badge-urgent",
    "return_pending": "badge-urgent",
}

PRIORITY_CLASS = {
    "low": "badge-muted",
    "normal": "badge-sent",
    "high": "badge-urgent",
}


@register.simple_tag
def status_class(value):
    return STATUS_CLASS.get(value, "badge-muted")


@register.simple_tag
def priority_class(value):
    return PRIORITY_CLASS.get(value, "badge-muted")


@register.filter(name="mask_fin_filter")
def mask_fin_filter(value):
    return mask_fin(value or "")


@register.simple_tag(takes_context=True)
def nav_active(context, *names):
    request = context.get("request")
    if not request:
        return ""
    match = getattr(request, "resolver_match", None)
    current = getattr(match, "url_name", "") or ""
    namespace = getattr(match, "namespace", "") or ""
    full = f"{namespace}:{current}" if namespace else current
    return "is-active" if current in names or full in names else ""
