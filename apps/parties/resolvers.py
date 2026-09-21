"""Party dual-read helpers — ResidentCompany remains ops SoT until cutover."""

from __future__ import annotations

from apps.parties.models import Party, Person
from apps.parties.services import PartyService
from apps.residents.models import ResidentCompany, ResidentEmployee


def party_for_company(company: ResidentCompany | None, *, ensure: bool = True) -> Party | None:
    if company is None:
        return None
    party = getattr(company, "party", None)
    if party is not None:
        return party
    existing = Party.objects.filter(legacy_resident_company=company).first()
    if existing:
        return existing
    if ensure:
        return PartyService.upsert_from_resident_company(company)
    return None


def person_for_employee(employee: ResidentEmployee | None, *, ensure: bool = True) -> Person | None:
    if employee is None:
        return None
    person = getattr(employee, "person", None)
    if person is not None:
        return person
    existing = Person.objects.filter(legacy_employee=employee).first()
    if existing:
        return existing
    if ensure:
        return PartyService.upsert_person_from_employee(employee)
    return None
