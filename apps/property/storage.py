"""Private storage for space drawings — reuse security private root."""

from apps.security.storage import PrivatePlanStorage, private_plan_storage

__all__ = ["PrivatePlanStorage", "private_plan_storage"]
