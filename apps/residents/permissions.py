"""ERP / portal authorization for resident profile and legal documents."""

from __future__ import annotations

from apps.accounts.models import Role
from apps.accounts.portal_scope import get_portal_scope


def user_can_manage_resident_profile(user) -> bool:
    """Admin / Management / Property FM — profil + hüquqi/bank + sənəd CRUD."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM}


def user_can_view_resident_legal_docs(user) -> bool:
    """ERP: hüquqi/bank/müqavilə/sənəd oxuma — eyni rollar."""
    return user_can_manage_resident_profile(user)


def user_can_view_resident_ops_summary(user) -> bool:
    """Reception: yalnız ad, status, mərtəbə/sahə (+ qonaq)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role in {
        Role.ADMIN,
        Role.MANAGEMENT,
        Role.PROPERTY_FM,
        Role.RECEPTION,
        Role.SERVICE_DESK,
    }


def user_is_reception_limited(user) -> bool:
    return bool(user and user.is_authenticated and user.role == Role.RECEPTION)


def user_can_access_portal_document(user, document) -> bool:
    """Portal: visible_to_resident + company in session scope."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(document, "visible_to_resident", False):
        return False
    if not document.company_id:
        return False
    if user.role != Role.RESIDENT_USER:
        # Staff may browse portal docs only for scoped companies if any
        return user_can_view_resident_legal_docs(user)
    # Prefer request-bound scope when available via thread-local callers;
    # callers should pass company_ids when known.
    return True


def user_can_access_portal_document_in_scope(user, document, company_ids) -> bool:
    if not user_can_access_portal_document(user, document):
        return False
    if user.role != Role.RESIDENT_USER:
        return user_can_view_resident_legal_docs(user)
    ids = set(company_ids or [])
    return document.company_id in ids


def portal_document_qs_for_request(request):
    from apps.documents.models import Document

    ids = getattr(request, "portal_company_ids", None)
    if ids is None:
        scope = getattr(request, "portal_scope", None) or get_portal_scope(request)
        ids = list(scope.company_ids) if scope else []
    ids = list(ids or [])
    if not ids:
        return Document.objects.none()
    return Document.objects.filter(
        company_id__in=ids,
        visible_to_resident=True,
    ).select_related("document_type", "company")
