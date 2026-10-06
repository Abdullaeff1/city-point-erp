"""Tests for AxTrax people sync card reassignment / deactivate."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM, sync_people_from_payload
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
        # Only Namik left in export — Ali orphaned
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
        ali = ResidentEmployee.objects.get(full_name="Əli Cumayev")
        namik = ResidentEmployee.objects.get(full_name="Namik Məhəmmədov")
        self.assertFalse(ali.is_active)
        self.assertEqual(ali.card_number, "")
        self.assertEqual(namik.card_number, "006001")
