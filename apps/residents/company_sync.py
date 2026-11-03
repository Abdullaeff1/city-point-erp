"""Single write path for ResidentCompany + Party.tax_id (VÖEN) sync."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import log_action
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.parties.resolvers import party_for_company
from apps.residents.models import CompanyStatus, ResidentCompany


def _sync_party_tax_id(company: ResidentCompany) -> Party | None:
    party = party_for_company(company, ensure=True)
    if party is None:
        return None
    voen = (company.voen or "").strip()
    status = PartyStatus.ACTIVE if company.status == CompanyStatus.ACTIVE else PartyStatus.INACTIVE
    changed = False
    if party.tax_id != voen:
        party.tax_id = voen
        changed = True
    if party.legal_name != company.name:
        party.legal_name = company.name
        party.brand_name = company.name
        changed = True
    if party.contact_email != (company.contact_email or ""):
        party.contact_email = company.contact_email or ""
        changed = True
    if party.status != status:
        party.status = status
        changed = True
    if changed:
        party.save()
    PartyRole.objects.get_or_create(
        party=party,
        role=PartyRoleCode.RESIDENT,
        defaults={"is_primary": True},
    )
    return party


def company_has_blocking_relations(company: ResidentCompany) -> bool:
    if company.documents.exists():
        return True
    party = Party.objects.filter(legacy_resident_company=company).first()
    if party is not None:
        if party.leases.exists():
            return True
        if hasattr(party, "invoices") and party.invoices.exists():
            return True
        if hasattr(party, "charges") and party.charges.exists():
            return True
    return False


@transaction.atomic
def save_resident_company(
    company: ResidentCompany,
    *,
    actor=None,
    create: bool | None = None,
    audit: bool = True,
) -> ResidentCompany:
    """Validate, save company, sync Party.tax_id from company.voen."""
    if create is None:
        create = company.pk is None
    company.full_clean()
    if company.is_archived and company.portal_active:
        raise ValidationError({"portal_active": _("Arxivdə olan şirkətin portalı aktiv ola bilməz.")})
    if actor is not None:
        if create and not company.created_by_id:
            company.created_by = actor
        company.updated_by = actor
    company.save()
    _sync_party_tax_id(company)
    if audit:
        log_action(
            action="resident_company.created" if create else "resident_company.updated",
            actor=actor,
            entity=company,
            new_values={"name": company.name, "voen": company.voen, "slug": company.slug},
            source="erp",
        )
    return company


@transaction.atomic
def archive_resident_company(company: ResidentCompany, *, actor=None) -> ResidentCompany:
    company.is_archived = True
    company.portal_active = False
    company.archived_at = timezone.now()
    company.archived_by = actor
    company.updated_by = actor
    company.full_clean()
    company.save(
        update_fields=[
            "is_archived",
            "portal_active",
            "archived_at",
            "archived_by",
            "updated_by",
            "updated_at",
        ]
    )
    _sync_party_tax_id(company)
    log_action(
        action="resident_company.archived",
        actor=actor,
        entity=company,
        new_values={"is_archived": True, "portal_active": False},
        source="erp",
    )
    return company


@transaction.atomic
def unarchive_resident_company(company: ResidentCompany, *, actor=None) -> ResidentCompany:
    """Restore from archive. Does NOT reopen portal — set portal_active separately."""
    company.is_archived = False
    company.archived_at = None
    company.archived_by = None
    company.updated_by = actor
    # portal_active stays as-is (normally False after archive)
    company.full_clean()
    company.save(
        update_fields=[
            "is_archived",
            "archived_at",
            "archived_by",
            "updated_by",
            "updated_at",
        ]
    )
    log_action(
        action="resident_company.unarchived",
        actor=actor,
        entity=company,
        new_values={"is_archived": False, "portal_active": company.portal_active},
        source="erp",
    )
    return company


@transaction.atomic
def delete_or_archive_resident_company(company: ResidentCompany, *, actor=None) -> str:
    """Hard-delete when safe; otherwise archive. Returns 'deleted' or 'archived'."""
    if company_has_blocking_relations(company):
        archive_resident_company(company, actor=actor)
        return "archived"
    log_action(
        action="resident_company.deleted",
        actor=actor,
        entity=company,
        old_values={"name": company.name, "slug": company.slug},
        source="erp",
    )
    company.delete()
    return "deleted"
