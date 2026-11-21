"""Unified document confidentiality / download ACL (M9)."""

from __future__ import annotations

from apps.accounts.models import Role
from apps.documents.models import (
    DOCUMENT_TYPE_BANK_CERTIFICATE,
    DOCUMENT_TYPE_COMPANY_EXTRACT,
    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
    DOCUMENT_TYPE_LEASE_CONTRACT,
    DOCUMENT_TYPE_LEASE_AMENDMENT,
    DOCUMENT_TYPE_VOEN,
    Document,
    DocumentSensitivity,
)

# Commercial / legal types must never become portal-public via a checkbox alone.
PORTAL_LOCKED_DOCUMENT_TYPES = frozenset(
    {
        DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
        DOCUMENT_TYPE_LEASE_CONTRACT,
        DOCUMENT_TYPE_LEASE_AMENDMENT,
        DOCUMENT_TYPE_VOEN,
        DOCUMENT_TYPE_BANK_CERTIFICATE,
        DOCUMENT_TYPE_COMPANY_EXTRACT,
    }
)


def document_type_code(document_type) -> str:
    return (getattr(document_type, "code", None) or "").strip()


def is_portal_locked_document_type(document_type) -> bool:
    return document_type_code(document_type) in PORTAL_LOCKED_DOCUMENT_TYPES


def sensitivity_for_new_document(*, document_type=None, visible_to_resident: bool = False) -> str:
    if is_portal_locked_document_type(document_type):
        return getattr(document_type, "default_sensitivity", None) or DocumentSensitivity.CONFIDENTIAL
    if visible_to_resident:
        return DocumentSensitivity.PUBLIC_RESIDENT
    if document_type is not None and getattr(document_type, "default_sensitivity", None):
        return document_type.default_sensitivity
    return DocumentSensitivity.CONFIDENTIAL


def clamp_portal_visibility(*, document_type=None, visible_to_resident: bool = False) -> bool:
    """Refuse portal visibility for commercial/legal document types."""
    if is_portal_locked_document_type(document_type):
        return False
    return bool(visible_to_resident)


def user_can_download_document(user, document: Document) -> bool:
    """Server-side gate for ERP/portal document downloads."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    sens = document.sensitivity or DocumentSensitivity.CONFIDENTIAL

    if sens == DocumentSensitivity.PUBLIC_RESIDENT:
        if document.visible_to_resident and document.company_id:
            from apps.residents.permissions import user_can_access_portal_document

            return user_can_access_portal_document(user, document)
        return role in {
            Role.ADMIN,
            Role.MANAGEMENT,
            Role.PROPERTY_FM,
            Role.ACCOUNTANT,
            Role.SERVICE_DESK,
        }

    if sens == DocumentSensitivity.INTERNAL:
        return role in {
            Role.ADMIN,
            Role.MANAGEMENT,
            Role.PROPERTY_FM,
            Role.ACCOUNTANT,
            Role.SERVICE_DESK,
            Role.SECURITY,
            Role.RECEPTION,
        }

    if sens == DocumentSensitivity.CONFIDENTIAL:
        return role in {Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM, Role.ACCOUNTANT}

    # RESTRICTED — şəxsiyyət / həssas
    return role in {Role.ADMIN, Role.MANAGEMENT, Role.ACCOUNTANT}
