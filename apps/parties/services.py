from django.db import transaction

from apps.core.services import Service
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType, Person, PersonKind
from apps.residents.models import CompanyStatus, ResidentCompany, ResidentEmployee


class PartyService(Service):
    @classmethod
    @transaction.atomic
    def upsert_from_resident_company(cls, company: ResidentCompany) -> Party:
        status = PartyStatus.ACTIVE if company.status == CompanyStatus.ACTIVE else PartyStatus.INACTIVE
        party, _ = Party.objects.update_or_create(
            legacy_resident_company=company,
            defaults={
                "party_type": PartyType.ORGANIZATION,
                "legal_name": company.name,
                "brand_name": company.name,
                "status": status,
                "contact_email": company.contact_email or "",
            },
        )
        PartyRole.objects.get_or_create(
            party=party,
            role=PartyRoleCode.RESIDENT,
            defaults={"is_primary": True},
        )
        return party

    @classmethod
    @transaction.atomic
    def upsert_person_from_employee(cls, employee: ResidentEmployee) -> Person:
        party = None
        if employee.company_id:
            party = PartyService.upsert_from_resident_company(employee.company)
        person, _ = Person.objects.update_or_create(
            legacy_employee=employee,
            defaults={
                "full_name": employee.full_name,
                "party": party,
                "person_kind": PersonKind.RESIDENT_EMPLOYEE,
                "is_active": employee.is_active,
            },
        )
        return person

    @classmethod
    def sync_all_from_legacy(cls) -> dict:
        parties = 0
        people = 0
        for company in ResidentCompany.objects.all():
            cls.upsert_from_resident_company(company)
            parties += 1
        for employee in ResidentEmployee.objects.select_related("company"):
            cls.upsert_person_from_employee(employee)
            people += 1
        return {"parties": parties, "people": people}
