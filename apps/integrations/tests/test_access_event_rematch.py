"""Rematch AccessEvent FKs when AxTrax emp-id reuse renamed the linked employee."""

from django.test import TestCase
from django.utils import timezone

from apps.integrations.access_event_rematch import rematch_access_events
from apps.integrations.axtrax_events_sync import _snapshot_name
from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM, sync_people_from_payload
from apps.integrations.models import ExternalIdentity
from apps.integrations.tests.test_people_card_sync import _payload, _row
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    ResidentCompany,
    ResidentEmployee,
)


class AccessEventRematchTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(name="L.B.Audit", slug="lbaudit-test")
        self.jala = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Jalə Anar Mirzəməmmədova",
            card_number="006109",
            is_active=True,
        )
        self.cemil = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Cəmil Eldar Eynullayev",
            card_number="006645",
            is_active=True,
        )

    def test_rematch_moves_events_to_snapshot_person(self):
        now = timezone.now()
        wrong = AccessEvent.objects.create(
            employee=self.jala,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=now,
            employee_name="Cəmil Eldar Eynullayev",
            card_number="006297",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        right = AccessEvent.objects.create(
            employee=self.jala,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=now,
            employee_name="Jalə Anar Mirzəməmmədova",
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )

        stats = rematch_access_events(dry_run=False, create_missing=True)
        wrong.refresh_from_db()
        right.refresh_from_db()

        self.assertEqual(wrong.employee_id, self.cemil.pk)
        self.assertEqual(wrong.card_number, "006297")
        self.assertEqual(wrong.company_name, "L.B.Audit")
        self.assertEqual(right.employee_id, self.jala.pk)
        self.assertGreaterEqual(stats["reassigned_events"], 1)

    def test_rematch_creates_archive_stub_when_person_missing(self):
        AccessEvent.objects.create(
            employee=self.jala,
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            employee_name="Vasif Asif Həsənov",
            card_number="006111",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        stats = rematch_access_events(dry_run=False, create_missing=True)
        stub = ResidentEmployee.objects.get(full_name="Vasif Asif Həsənov")
        self.assertFalse(stub.is_active)
        self.assertEqual(stub.company_id, self.company.pk)
        ev = AccessEvent.objects.get(employee_name="Vasif Asif Həsənov")
        self.assertEqual(ev.employee_id, stub.pk)
        self.assertEqual(stats["created_employees"], 1)

    def test_empty_name_wrong_card_moves_to_named_card_owner(self):
        now = timezone.now()
        AccessEvent.objects.create(
            employee=self.cemil,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=now,
            employee_name="Cəmil Eldar Eynullayev",
            card_number="006297",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        orphan = AccessEvent.objects.create(
            employee=self.jala,
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=now,
            employee_name="",
            card_number="006297",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        rematch_access_events(dry_run=False, create_missing=True)
        orphan.refresh_from_db()
        self.assertEqual(orphan.employee_id, self.cemil.pk)
        self.assertEqual(orphan.employee_name, "Cəmil Eldar Eynullayev")


class IdentitySplitPeopleSyncTests(TestCase):
    def test_emp_id_reuse_does_not_rename_old_person(self):
        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=13,
                        dept_name="L.B.Audit",
                        emp_id=1075,
                        first="Cəmil Eldar",
                        last="Eynullayev",
                        identification="006297",
                        enabled=True,
                    ),
                ]
            )
        )
        cemil = ResidentEmployee.objects.get(full_name="Cəmil Eldar Eynullayev")
        cemil_pk = cemil.pk

        sync_people_from_payload(
            _payload(
                [
                    _row(
                        dept_id=13,
                        dept_name="L.B.Audit",
                        emp_id=1075,
                        first="Jalə Anar",
                        last="Mirzəməmmədova",
                        identification="006109",
                        enabled=True,
                    ),
                    _row(
                        dept_id=13,
                        dept_name="L.B.Audit",
                        emp_id=2000,
                        first="Cəmil Eldar",
                        last="Eynullayev",
                        identification="006645",
                        enabled=True,
                    ),
                ]
            )
        )
        cemil.refresh_from_db()
        jala = ResidentEmployee.objects.get(full_name="Jalə Anar Mirzəməmmədova")
        self.assertEqual(cemil.pk, cemil_pk)
        self.assertEqual(cemil.full_name, "Cəmil Eldar Eynullayev")
        self.assertEqual(cemil.card_number, "006645")
        self.assertEqual(jala.card_number, "006109")
        self.assertNotEqual(jala.pk, cemil_pk)

        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(ResidentEmployee)
        self.assertEqual(
            ExternalIdentity.objects.get(
                system=AXTRAX_SYSTEM, external_id="emp:1075", entity_type=ct
            ).entity_id,
            jala.pk,
        )
        self.assertEqual(
            ExternalIdentity.objects.get(
                system=AXTRAX_SYSTEM, external_id="emp:2000", entity_type=ct
            ).entity_id,
            cemil.pk,
        )


class SnapshotNameTests(TestCase):
    def test_snapshot_name_prefers_axtrax_row(self):
        from types import SimpleNamespace

        employee = SimpleNamespace(full_name="Jalə Anar Mirzəməmmədova")
        self.assertEqual(
            _snapshot_name({"full_name": "Cəmil Eldar Eynullayev"}, employee),
            "Cəmil Eldar Eynullayev",
        )
        self.assertEqual(
            _snapshot_name({"full_name": ""}, employee),
            "Jalə Anar Mirzəməmmədova",
        )
