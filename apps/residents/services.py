"""Resident employee onboarding / access card order (portal)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.parties.services import PartyService
from apps.residents.models import AccessLevel, ResidentEmployee
from apps.tickets.models import TicketAttachment, TicketSubcategory, TicketType
from apps.tickets.services import create_ticket_from_portal

ALLOWED_ID_EXT = (".pdf", ".jpg", ".jpeg", ".png")
MAX_ID_BYTES = 10 * 1024 * 1024


def validate_id_document(uploaded) -> None:
    if not uploaded:
        raise ValidationError(_("Şəxsiyyət vəsiqəsi mütləqdir."))
    name = (getattr(uploaded, "name", "") or "").lower()
    if not name.endswith(ALLOWED_ID_EXT):
        raise ValidationError(_("Yalnız PDF, JPG və ya PNG fayl yükləyin."))
    size = getattr(uploaded, "size", 0) or 0
    if size > MAX_ID_BYTES:
        raise ValidationError(_("Fayl ölçüsü 10 MB-dan böyük ola bilməz."))


@transaction.atomic
def create_employee_card_order(*, company, requester, full_name: str, id_document, access_level: str = AccessLevel.LEVEL_1):
    """Create employee (no card) + security card-order ticket + ID attachment."""
    name = (full_name or "").strip()
    if not name:
        raise ValidationError(_("Əməkdaşın adı mütləqdir."))
    if company is None or getattr(company, "is_internal", False):
        raise ValidationError(_("Bu şirkət üçün portal əlavəsi icazəli deyil."))
    validate_id_document(id_document)
    if access_level not in {AccessLevel.LEVEL_1, AccessLevel.LEVEL_2}:
        raise ValidationError(_("Kart səviyyəsi 1 və ya 2 olmalıdır."))

    sub = (
        TicketSubcategory.objects.select_related("category", "routing_rule")
        .filter(slug="card-order", category__slug="security", is_active=True)
        .first()
    )
    if not sub:
        raise ValidationError(_("Kart sifarişi kateqoriyası tapılmadı. Taxonomy seed edin."))

    raw_name = getattr(id_document, "name", "id-document.pdf") or "id-document.pdf"
    content = id_document.read()
    if hasattr(id_document, "seek"):
        id_document.seek(0)

    employee = ResidentEmployee(
        company=company,
        full_name=name[:160],
        card_number="",
        access_level=access_level,
        is_active=True,
    )
    employee.id_document.save(raw_name, ContentFile(content), save=False)
    employee.save()
    PartyService.upsert_person_from_employee(employee)

    level_label = dict(AccessLevel.choices).get(access_level, access_level)
    description = (
        f"Portal kart sifarişi (əvvəlki fiziki akt əvəzinə).\n"
        f"Şirkət: {company.name}\n"
        f"Əməkdaş: {employee.full_name}\n"
        f"İstənilən kart səviyyəsi (portal): {level_label}\n"
        f"Faktiki səviyyə AxTraxNG access group sync-indən gələcək.\n"
        f"Kart nömrəsi təyin olunmayıb — AxTrax / təhlükəsizlik tərəfindən veriləcək.\n"
        f"Şəxsiyyət vəsiqəsi nüsxəsi əlavə olunub."
    )
    ticket = create_ticket_from_portal(
        company=company,
        requester=requester,
        ticket_type=TicketType.SERVICE_REQUEST,
        category=sub.category,
        subcategory=sub,
        description=description,
        related_employee=employee,
    )
    TicketAttachment.objects.create(ticket=ticket, file=ContentFile(content, name=raw_name))
    return employee, ticket
