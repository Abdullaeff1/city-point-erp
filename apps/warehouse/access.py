"""Warehouse ACL helpers (Phase 4.4.2.2)."""

from __future__ import annotations

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission


def can_view_warehouse(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user_has_permission(user, "warehouse.view")


def can_mutate_warehouse(user) -> bool:
    """Stock/SKU mutations. Management remains read-only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == Role.MANAGEMENT:
        return False
    return user_has_permission(user, "warehouse.edit")


def can_count_stocktake(user) -> bool:
    """Enter / finish physical counts. Same gate as warehouse.edit today."""
    return can_mutate_warehouse(user)


def can_post_stocktake_adjustments(user) -> bool:
    """
    Post variance adjustments. Catalog has no separate stocktake.post code;
    Management is view-only (warehouse.view) and cannot post.
    """
    return can_mutate_warehouse(user)
