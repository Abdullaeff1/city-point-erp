from django.db import transaction

from apps.audit.services import log_action
from apps.core.services import Service
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType, Person, PersonKind
from apps.residents.models import CompanyStatus, ResidentCompany, ResidentEmployee


class PartyService(Service):
    @classmethod
    @transaction.atomic
    def upsert_from_resident_company(cls, company: ResidentCompany, *, actor=None, audit: bool = True) -> Party:
        status = PartyStatus.ACTIVE if company.status == CompanyStatus.ACTIVE else PartyStatus.INACTIVE
        defaults = {
            "party_type": PartyType.ORGANIZATION,
            "legal_name": company.name,
            "brand_name": company.name,
            "status": status,
            "contact_email": company.contact_email or "",
            "contact_phone": (company.phone or "").strip(),
            "tax_id": (company.voen or "").strip(),
        }
        party, created = Party.objects.update_or_create(
            legacy_resident_company=company,
            defaults=defaults,
        )
        PartyRole.objects.get_or_create(
            party=party,
            role=PartyRoleCode.RESIDENT,
            defaults={"is_primary": True},
        )
        if audit:
            log_action(
                action="party.upserted",
                actor=actor,
                entity=party,
                new_values={
                    "created": created,
                    "legal_name": party.legal_name,
                    "tax_id": party.tax_id,
                    "legacy_company_id": company.pk,
                },
                source="parties",
            )
        return party

    @classmethod
    @transaction.atomic
    def upsert_person_from_employee(cls, employee: ResidentEmployee, *, actor=None, audit: bool = True) -> Person:
        party = None
        if employee.company_id:
            party = PartyService.upsert_from_resident_company(employee.company, actor=actor, audit=audit)
        person, created = Person.objects.update_or_create(
            legacy_employee=employee,
            defaults={
                "full_name": employee.full_name,
                "party": party,
                "person_kind": PersonKind.RESIDENT_EMPLOYEE,
                "is_active": employee.is_active,
            },
        )
        if audit:
            log_action(
                action="person.upserted",
                actor=actor,
                entity=person,
                new_values={
                    "created": created,
                    "full_name": person.full_name,
                    "legacy_employee_id": employee.pk,
                    "party_id": party.pk if party else None,
                },
                source="parties",
            )
        return person

    @classmethod
    def sync_all_from_legacy(cls) -> dict:
        parties = 0
        people = 0
        for company in ResidentCompany.objects.all():
            cls.upsert_from_resident_company(company, audit=False)
            parties += 1
        for employee in ResidentEmployee.objects.select_related("company"):
            cls.upsert_person_from_employee(employee, audit=False)
            people += 1
        return {"parties": parties, "people": people}
