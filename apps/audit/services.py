from django.contrib.contenttypes.models import ContentType

from apps.audit.models import AuditLog


def log_action(
    *,
    action: str,
    actor=None,
    entity=None,
    old_values=None,
    new_values=None,
    source: str = "erp",
    ip_address=None,
    correlation_id: str = "",
) -> AuditLog:
    ct = None
    eid = None
    repr_ = ""
    if entity is not None:
        ct = ContentType.objects.get_for_model(entity, for_concrete_model=False)
        eid = getattr(entity, "pk", None)
        repr_ = str(entity)[:255]
    return AuditLog.objects.create(
        action=action,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        entity_type=ct,
        entity_id=eid,
        object_repr=repr_,
        old_values=old_values,
        new_values=new_values,
        source=source,
        ip_address=ip_address,
        correlation_id=correlation_id or "",
    )
