"""ERP / portal authorization for resident profile and legal documents."""

from __future__ import annotations

from apps.accounts.models import Role
from apps.accounts.portal_scope import get_portal_scope
from apps.rbac.services import user_has_permission


def user_can_manage_resident_profile(user) -> bool:
    """Profil + hüquqi/bank + sənəd CRUD — ``resident.edit`` (Admin / Management / explicit)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user_has_permission(user, "resident.edit")


def user_can_view_resident_legal_docs(user) -> bool:
    """ERP: hüquqi/bank/müqavilə/sənəd oxuma — eyni qrant."""
    return user_can_manage_resident_profile(user)


def user_can_view_resident_directory(user) -> bool:
    """Business-contact directory — not legal/bank/identity/attendance."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_has_permission(user, "resident.directory.view"):
        return True
    # Full resident.view still implies directory access for staff who already had it.
    return user_has_permission(user, "resident.view") and user.role in {
        Role.ADMIN,
        Role.MANAGEMENT,
        Role.SERVICE_DESK,
        Role.RECEPTION,
        Role.SALES,
        Role.ACCOUNTANT,
    }


def user_can_view_resident_ops_summary(user) -> bool:
    """Reception: yalnız ad, status, mərtəbə/sahə (+ qonaq)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {
        Role.ADMIN,
        Role.MANAGEMENT,
        Role.RECEPTION,
        Role.SERVICE_DESK,
    }


def user_is_reception_limited(user) -> bool:
    return bool(user and user.is_authenticated and user.role == Role.RECEPTION)


def user_can_access_portal_document(user, document) -> bool:
    """Portal: visible_to_resident; company checked via ``*_in_scope``."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(document, "visible_to_resident", False):
        return False
    if not document.company_id:
        return False
    if user.role != Role.RESIDENT_USER:
        return user_can_view_resident_legal_docs(user)
    return True


def user_can_access_portal_document_in_scope(user, document, company_ids) -> bool:
    if not user_can_access_portal_document(user, document):
        return False
    from apps.accounts.object_scope import company_accessible

    ids = list(company_ids or [])
    if user.role != Role.RESIDENT_USER:
        if not user_can_view_resident_legal_docs(user):
            return False
        # Staff browsing portal: when scope ids present, require company ∈ scope
        if ids:
            return int(document.company_id) in {int(i) for i in ids}
        return True
    return company_accessible(user, document.company_id, company_ids=ids or None)


def portal_document_qs_for_request(request):
    from apps.documents.models import Document

    ids = getattr(request, "portal_company_ids", None)
    if ids is None:
        scope = getattr(request, "portal_scope", None) or get_portal_scope(request)
        ids = list(scope.company_ids) if scope else []
    ids = list(ids or [])
    if not ids:
        return Document.objects.none()
    from apps.documents.models import DocumentSensitivity

    return Document.objects.filter(
        company_id__in=ids,
        visible_to_resident=True,
        sensitivity=DocumentSensitivity.PUBLIC_RESIDENT,
    ).select_related("document_type", "company")
