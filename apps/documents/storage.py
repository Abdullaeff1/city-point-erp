"""Private document storage — outside public /media/."""

from apps.security.storage import PrivatePlanStorage, private_plan_storage

PrivateDocumentStorage = PrivatePlanStorage
private_document_storage = private_plan_storage

__all__ = ["PrivateDocumentStorage", "private_document_storage"]
