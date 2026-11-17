"""Tests for AxTrax people sync card reassignment / deactivate."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.integrations.axtrax_people_sync import (
    AXTRAX_SYSTEM,
    _find_unlinked_employee_by_name,
    sync_people_from_payload,
)
from apps.integrations.models import ExternalIdentity
from apps.residents.models import ResidentCompany, ResidentEmployee


def _payload(rows, access_groups=None):
    return {
        "source": "test",
        "row_count": len(rows),
        "access_groups": access_groups or [],
        "rows": rows,
    }


def _row(*, dept_id, dept_name, emp_id, first, last, identification, enabled=True):
    return {
        "department_id": dept_id,
        "department_name": dept_name,
        "employee_id": emp_id,
        "first_name": first,
        "middle_name": "",
        "last_name": last,
        "email": "",
        "mobile": "",
        "identification": identification,
        "access_group_id": 1,
        "access_group_name": "Front",
        "has_turn_back": False,
        "is_enabled": enabled,
        "card_code": "999",
        "card_status": 1,
    }


class AxTraxPeopleCardSyncTests(TestCase):
    def test_card_moves_from_former_to_new_employee(self):
        # First sync: Ali has 006001 at Simbrella
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=10,
                        dept_name="Simbrella",
                        emp_id=631,
                        first="Əli",
                        last="Cumayev",
                        identification="006001",
                        enabled=True,
                    ),
                    _row(
                        dept_id=20,
                        dept_name="City Point",
                        emp_id=1122,
                        first="Namik",
                        last="Məhəmmədov",
                        identification="006536",
                        enabled=True,
                    ),
                ]
            )
        )
        ali = ResidentEmployee.objects.get(full_name="Əli Cumayev")
        namik = ResidentEmployee.objects.get(full_name="Namik Məhəmmədov")
        self.assertEqual(ali.card_number, "006001")
        self.assertEqual(namik.card_number, "006536")

        # Second sync: Ali left (disabled, no badge); Namik has 006001
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=10,
                        dept_name="Simbrella",
                        emp_id=631,
                        first="Əli",
                        last="Cumayev",
                        identification="",
                        enabled=False,
                    ),
                    _row(
                        dept_id=20,
                        dept_name="City Point",
                        emp_id=1122,
                        first="Namik",
                        last="Məhəmmədov",
                        identification="006001",
                        enabled=True,
                    ),
                ]
            )
        )
        ali.refresh_from_db()
        namik.refresh_from_db()
        self.assertFalse(ali.is_active)
        self.assertEqual(ali.card_number, "")
        self.assertTrue(namik.is_active)
        self.assertEqual(namik.card_number, "006001")
        self.assertEqual(
            ResidentEmployee.objects.filter(card_number="006001").count(),
            1,
        )

    def test_duplicate_badge_prefers_enabled_employee(self):
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=10,
                        dept_name="Simbrella",
                        emp_id=631,
                        first="Əli",
                        last="Cumayev",
                        identification="006001",
                        enabled=False,
                    ),
                    _row(
                        dept_id=20,
                        dept_name="City Point",
                        emp_id=1122,
                        first="Namik",
                        last="Məhəmmədov",
                        identification="006001",
                        enabled=True,
                    ),
                ]
            )
        )
        ali = ResidentEmployee.objects.get(full_name="Əli Cumayev")
        namik = ResidentEmployee.objects.get(full_name="Namik Məhəmmədov")
        self.assertEqual(namik.card_number, "006001")
        self.assertEqual(ali.card_number, "")
        self.assertFalse(ali.is_active)

    def test_missing_from_export_deactivates_and_clears_card(self):
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=10,
                        dept_name="Simbrella",
                        emp_id=631,
                        first="Əli",
                        last="Cumayev",
                        identification="006001",
                        enabled=True,
                    ),
                ]
            )
        )
        ali = ResidentEmployee.objects.get(full_name="Əli Cumayev")
        from django.utils import timezone

        from apps.residents.models import AccessEvent, AccessEventType, AccessResult

        AccessEvent.objects.create(
            employee=ali,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            employee_name=ali.full_name,
            card_number="006001",
            reader_name="F1TurIN",
        )
        # Only Namik left in export — Ali orphaned (deleted from AxTrax)
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=20,
                        dept_name="City Point",
                        emp_id=1122,
                        first="Namik",
                        last="Məhəmmədov",
                        identification="006001",
                        enabled=True,
                    ),
                ]
            )
        )
        ali.refresh_from_db()
        namik = ResidentEmployee.objects.get(full_name="Namik Məhəmmədov")
        self.assertFalse(ali.is_active)
        self.assertIsNotNone(ali.deactivated_at)
        self.assertEqual(ali.card_number, "")
        self.assertEqual(namik.card_number, "006001")
        # Soft-archive only: row + punch history must remain in ERP
        self.assertTrue(ResidentEmployee.objects.filter(pk=ali.pk).exists())
        self.assertEqual(AccessEvent.objects.filter(employee=ali).count(), 1)


class EventCardSnapshotTests(TestCase):
    def test_event_stores_badge_not_internal_code(self):
        from types import SimpleNamespace

        from apps.integrations.axtrax_events_sync import _snapshot_card, _snapshot_company

        employee = SimpleNamespace(
            card_number="006445",
            company=SimpleNamespace(pk=9, name="Demo Co"),
            company_id=9,
        )
        # Explicit printed badge on the row wins over employee current badge
        self.assertEqual(
            _snapshot_card({"badge_number": "006109", "card_code": "25037"}, employee),
            "006109",
        )
        # Otherwise employee badge (printed) beats internal iCardCode
        self.assertEqual(_snapshot_card({"card_code": "25037"}, employee), "006445")
        self.assertEqual(_snapshot_card({"card_code": "25037"}, None), "25037")
        self.assertEqual(_snapshot_card({"card_code": "0"}, SimpleNamespace(card_number="")), "")
        cid, cname = _snapshot_company(employee)
        self.assertEqual(cid, 9)
        self.assertEqual(cname, "Demo Co")


class AxTraxEmpAliasNameLockTests(TestCase):
    def test_alias_628_does_not_recreate_arzu_name(self):
        """L.B.Audit: emp:628 (ARZU) must attach to emp:1662 (İsmayıl), not twin active row."""
        from apps.integrations.axtrax_people_sync import AXTRAX_DISPLAY_NAME_LOCKS

        dept = "L.B.Audit"
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=13,
                        dept_name=dept,
                        emp_id=1662,
                        first="Nərgiz",
                        last="Məmmədova",
                        identification="003959",
                        enabled=True,
                    ),
                ]
            )
        )
        # Force middle name via second sync with alias bad name still in AxTrax
        rows = [
            {
                "department_id": 13,
                "department_name": dept,
                "employee_id": 1662,
                "first_name": "Nərgiz",
                "middle_name": "İsmayıl",
                "last_name": "Məmmədova",
                "email": "",
                "mobile": "",
                "identification": "003959",
                "access_group_id": 1,
                "access_group_name": "Front",
                "has_turn_back": False,
                "is_enabled": True,
                "card_code": "1",
                "card_status": 1,
            },
            {
                "department_id": 13,
                "department_name": dept,
                "employee_id": 628,
                "first_name": "NƏRGİZ",
                "middle_name": "ARZU",
                "last_name": "MƏMMƏDOVA",
                "email": "",
                "mobile": "",
                "identification": "006299",
                "access_group_id": 1,
                "access_group_name": "Front",
                "has_turn_back": False,
                "is_enabled": True,
                "card_code": "2",
                "card_status": 1,
            },
        ]
        sync_people_from_payload(_payload(rows))

        locked = AXTRAX_DISPLAY_NAME_LOCKS[1662]
        active = list(
            ResidentEmployee.objects.filter(company__name=dept, is_active=True).order_by("pk")
        )
        nergiz_active = [e for e in active if "Nərgiz" in e.full_name or "NƏRG" in e.full_name]
        self.assertEqual(len(nergiz_active), 1, [e.full_name for e in nergiz_active])
        self.assertEqual(nergiz_active[0].full_name, locked)
        self.assertFalse(
            ResidentEmployee.objects.filter(
                company__name=dept, is_active=True, full_name__icontains="ARZU"
            ).exists()
        )
        ct = ContentType.objects.get_for_model(ResidentEmployee)
        eids = set(
            ExternalIdentity.objects.filter(
                system=AXTRAX_SYSTEM,
                entity_type=ct,
                entity_id=nergiz_active[0].pk,
            ).values_list("external_id", flat=True)
        )
        self.assertIn("emp:1662", eids)
        self.assertIn("emp:628", eids)


class AxTraxNameMatchAmbiguityTests(TestCase):
    def test_duplicate_unlinked_names_skip(self):
        company = ResidentCompany.objects.create(name="Amb Co", slug="amb-co")
        ResidentEmployee.objects.create(company=company, full_name="Eyni Ad", is_active=True)
        ResidentEmployee.objects.create(company=company, full_name="Eyni Ad", is_active=True)
        self.assertIsNone(_find_unlinked_employee_by_name(company, "Eyni Ad"))
        only = ResidentEmployee.objects.create(company=company, full_name="Tək Ad", is_active=True)
        self.assertEqual(_find_unlinked_employee_by_name(company, "Tək Ad").pk, only.pk)
