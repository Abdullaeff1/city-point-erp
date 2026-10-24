"""ACL helpers for security floor plans."""

from __future__ import annotations

from apps.accounts.models import Role


def can_view_security_plans(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.SECURITY, Role.ADMIN, Role.MANAGEMENT}


def can_view_floor_patrol(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.SECURITY, Role.ADMIN, Role.MANAGEMENT}


def can_edit_floor_patrol(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.SECURITY, Role.ADMIN}


def can_edit_security_plans(user) -> bool:
    """Upload, activate, pin/device mutate — Security + Admin only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.SECURITY, Role.ADMIN}


def device_allowed_on_plan(plan, device) -> bool:
    from apps.security.models import DeviceType, PlanCategory

    cat = plan.category
    dtype = device.device_type
    if cat == PlanCategory.MIXED:
        return True
    if cat == PlanCategory.CAMERAS:
        return dtype == DeviceType.CAMERA
    if cat == PlanCategory.SIGNALING:
        return dtype in {DeviceType.ALARM_PANEL, DeviceType.SENSOR}
    return False
