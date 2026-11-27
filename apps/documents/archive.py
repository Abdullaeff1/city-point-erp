"""Private document archive (Decision 08) — Management/Admin global browse with combined filters.

Non-management staff never get the global archive: ``archive_queryset_for`` returns an empty
queryset and the ERP view raises ``PermissionDenied``. Department users keep working through their
own module screens (ticket / work order / procurement / finance).
"""

from __future__ import annotations

from datetime import date

from django.core.paginator import Paginator
from django.db.models import Q, QuerySet

from apps.accounts.models import Role
from apps.documents.models import Document, DocumentSensitivity

ARCHIVE_PAGE_SIZE = 50

SOURCE_FINANCE = "finance"
SOURCE_TICKET = "ticket"
SOURCE_CRM = "crm"
SOURCE_WORK_ORDER = "wo"
SOURCE_PROCUREMENT = "procurement"
SOURCE_LEASE = "lease"
SOURCE_CORRESPONDENCE = "correspondence"
SOURCE_RESIDENT = "resident"
SOURCE_OTHER = "other"

MODULE_SOURCES = (
    (SOURCE_FINANCE, "Maliyyə"),
    (SOURCE_TICKET, "Sorğu (ticket)"),
    (SOURCE_CRM, "CRM / təklif"),
    (SOURCE_WORK_ORDER, "İş sifarişi"),
    (SOURCE_PROCUREMENT, "Təchizat"),
    (SOURCE_LEASE, "İcarə"),
    (SOURCE_CORRESPONDENCE, "Kargüzarlıq"),
    (SOURCE_RESIDENT, "Rezident"),
    (SOURCE_OTHER, "Digər"),
)

CRM_DOCUMENT_TYPE_CODES = ("offer_pdf",)

# Document types created by the Finance evidence flow (see billing.evidence_services).
FINANCE_DOCUMENT_TYPE_CODES = ("invoice_official", "payment_instruction")

VISIBILITY_PORTAL = "portal"
VISIBILITY_INTERNAL = "internal"
VISIBILITY_CHOICES = (
    (VISIBILITY_PORTAL, "Portala açıq"),
    (VISIBILITY_INTERNAL, "Daxili"),
)

FILTER_KEYS = (
    "type",
    "source",
    "company",
    "supplier",
    "space",
    "related",
    "date_from",
    "date_to",
    "visibility",
    "uploader",
    "q",
)


def can_browse_archive(user) -> bool:
    """Only Management and Admin browse the global private archive."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) in {Role.MANAGEMENT, Role.ADMIN}


def _source_predicates() -> list[tuple[str, Q]]:
    """Ordered (source, predicate) pairs — precedence mirrors ``module_source``."""
    return [
        (
            SOURCE_FINANCE,
            Q(invoice__isnull=False) | Q(document_type__code__in=FINANCE_DOCUMENT_TYPE_CODES),
        ),
        (SOURCE_TICKET, Q(ticket__isnull=False)),
        (
            SOURCE_CRM,
            Q(offer__isnull=False) | Q(document_type__code__in=CRM_DOCUMENT_TYPE_CODES),
        ),
        (SOURCE_WORK_ORDER, Q(work_order__isnull=False)),
        (
            SOURCE_PROCUREMENT,
            Q(purchase_request__isnull=False) | Q(purchase_order__isnull=False),
        ),
        (SOURCE_LEASE, Q(lease__isnull=False) | Q(parent_document__isnull=False)),
        (SOURCE_CORRESPONDENCE, ~Q(direction="")),
        (SOURCE_RESIDENT, Q(company__isnull=False)),
    ]


def module_source(doc: Document) -> str:
    """finance|ticket|crm|wo|procurement|lease|correspondence|resident|other."""
    type_code = getattr(getattr(doc, "document_type", None), "code", "") or ""
    if doc.invoice_id or type_code in FINANCE_DOCUMENT_TYPE_CODES:
        return SOURCE_FINANCE
    if doc.ticket_id:
        return SOURCE_TICKET
    if doc.offer_id or type_code in CRM_DOCUMENT_TYPE_CODES:
        return SOURCE_CRM
    if doc.work_order_id:
        return SOURCE_WORK_ORDER
    if doc.purchase_request_id or doc.purchase_order_id:
        return SOURCE_PROCUREMENT
    if doc.lease_id or doc.parent_document_id:
        return SOURCE_LEASE
    if doc.direction:
        return SOURCE_CORRESPONDENCE
    if doc.company_id:
        return SOURCE_RESIDENT
    return SOURCE_OTHER


def module_source_label(source: str) -> str:
    return dict(MODULE_SOURCES).get(source, source)


def _source_q(source: str) -> Q | None:
    predicates = _source_predicates()
    seen: Q | None = None
    for code, pred in predicates:
        if code == source:
            return pred if seen is None else (pred & ~seen)
        seen = pred if seen is None else (seen | pred)
    if source == SOURCE_OTHER and seen is not None:
        return ~seen
    return None


def _parse_date(raw) -> date | None:
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_archive_filters(data) -> dict:
    """Normalise a GET QueryDict / dict into the filter dict used by the queryset helper."""
    out = {}
    for key in FILTER_KEYS:
        raw = data.get(key) if data is not None else None
        out[key] = (raw or "").strip() if isinstance(raw, str) else (raw or "")
    out["date_from"] = _parse_date(out.get("date_from"))
    out["date_to"] = _parse_date(out.get("date_to"))
    return out


def archive_queryset_for(user, filters: dict | None = None) -> QuerySet[Document]:
    """Full private archive for Management/Admin; empty for everyone else."""
    if not can_browse_archive(user):
        return Document.objects.none()
    filters = filters or {}
    qs = Document.objects.select_related(
        "company",
        "space",
        "document_type",
        "party",
        "created_by",
        "ticket",
        "offer",
        "work_order",
        "purchase_request",
        "purchase_order",
        "invoice",
        "lease",
    )

    type_code = (filters.get("type") or "").strip()
    if type_code:
        qs = qs.filter(document_type__code=type_code)

    source = (filters.get("source") or "").strip()
    if source:
        pred = _source_q(source)
        if pred is not None:
            qs = qs.filter(pred)

    company = filters.get("company")
    if company not in (None, ""):
        try:
            qs = qs.filter(company_id=int(company))
        except (TypeError, ValueError):
            qs = qs.none()

    supplier = (str(filters.get("supplier") or "")).strip()
    if supplier:
        try:
            qs = qs.filter(party_id=int(supplier))
        except ValueError:
            qs = qs.none()

    space = filters.get("space")
    if space not in (None, ""):
        try:
            qs = qs.filter(space_id=int(space))
        except (TypeError, ValueError):
            qs = qs.none()

    related = (filters.get("related") or "").strip()
    if related:
        related_q = (
            Q(ticket__code__icontains=related)
            | Q(work_order__code__icontains=related)
            | Q(purchase_request__code__icontains=related)
            | Q(purchase_order__code__icontains=related)
            | Q(invoice__code__icontains=related)
            | Q(lease__code__icontains=related)
            | Q(registry_number__icontains=related)
            | Q(title__icontains=related)
        )
        # Offer numbers are integer PKs — exact match when digits-only.
        if related.isdigit():
            related_q = related_q | Q(offer_id=int(related))
        qs = qs.filter(related_q)

    date_from = _parse_date(filters.get("date_from"))
    date_to = _parse_date(filters.get("date_to"))
    if date_from:
        qs = qs.filter(published_at__gte=date_from)
    if date_to:
        qs = qs.filter(published_at__lte=date_to)

    visibility = (filters.get("visibility") or "").strip()
    if visibility == VISIBILITY_PORTAL:
        qs = qs.filter(
            visible_to_resident=True, sensitivity=DocumentSensitivity.PUBLIC_RESIDENT
        )
    elif visibility == VISIBILITY_INTERNAL:
        qs = qs.exclude(
            visible_to_resident=True, sensitivity=DocumentSensitivity.PUBLIC_RESIDENT
        )

    uploader = filters.get("uploader")
    if uploader not in (None, ""):
        try:
            qs = qs.filter(created_by_id=int(uploader))
        except (TypeError, ValueError):
            qs = qs.none()

    q = (filters.get("q") or "").strip()
    if q:
        text_q = (
            Q(title__icontains=q)
            | Q(company__name__icontains=q)
            | Q(registry_number__icontains=q)
            | Q(external_reference__icontains=q)
            | Q(party__legal_name__icontains=q)
            | Q(party__brand_name__icontains=q)
            | Q(ticket__code__icontains=q)
            | Q(work_order__code__icontains=q)
            | Q(purchase_request__code__icontains=q)
            | Q(purchase_order__code__icontains=q)
            | Q(invoice__code__icontains=q)
        )
        if q.isdigit():
            text_q = text_q | Q(offer_id=int(q))
        qs = qs.filter(text_q)

    return qs.order_by("-published_at", "-id")


def paginate_archive(qs, page):
    """Return the page object (50 per page); ``page.paginator.count`` is the authorized total."""
    return Paginator(qs, ARCHIVE_PAGE_SIZE).get_page(page)
