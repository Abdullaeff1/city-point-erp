"""Phase 10 — incoming letter → reply → version approval → dispatch."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.documents.access import clamp_portal_visibility, user_can_download_document
from apps.documents.correspondence import (
    allocate_registry_number,
    filter_correspondence,
    prepare_outgoing_reply,
    record_dispatch,
    register_incoming_letter,
    route_correspondence,
    _approved_version_for,
)
from apps.documents.models import (
    DOCUMENT_TYPE_INCOMING_LETTER,
    CorrespondenceDirection,
    CorrespondenceStatus,
    Document,
    DocumentDispatch,
    DocumentVersion,
)
from apps.documents.services import DocumentService
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.models import TicketDepartment
from apps.workflows.models import ApprovalStatus

User = get_user_model()


def _pdf(name: str, body: bytes = b"%PDF-1.4 letter") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class Phase10CorrespondenceFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p10-fm",
            email="p10-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="p10-mgmt",
            email="p10-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="p10-sales",
            email="p10-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.company = ResidentCompany.objects.create(
            name="ASBC Demo", slug="p10-asbc", portal_active=True
        )
        self.other_co = ResidentCompany.objects.create(
            name="Other Co", slug="p10-other", portal_active=True
        )
        self.dept, _ = TicketDepartment.objects.get_or_create(
            code="property", defaults={"name": "Əmlak / FM"}
        )

    def test_http_incoming_to_dispatch_walkthrough(self):
        self.client.force_login(self.fm)
        # Register incoming (letter 19 Nov, received 21 Nov)
        r = self.client.post(
            reverse("erp:correspondence_list"),
            {
                "action": "register_incoming",
                "title": "İcarə müddətinin uzadılması xahişi",
                "external_reference": "ASBC-LET-2026-19",
                "letter_date": "2026-11-19",
                "received_at": "2026-11-21",
                "company_id": str(self.company.pk),
                "department_id": str(self.dept.pk),
                "submit_token": "reg1",
                "file": _pdf("incoming.pdf"),
            },
        )
        self.assertEqual(r.status_code, 302)
        incoming = Document.objects.get(external_reference="ASBC-LET-2026-19")
        self.assertTrue(incoming.registry_number.startswith("IN-"))
        self.assertEqual(incoming.document_date, date(2026, 11, 19))
        self.assertEqual(incoming.received_at, date(2026, 11, 21))
        self.assertFalse(incoming.visible_to_resident)
        self.assertEqual(
            clamp_portal_visibility(
                document_type=incoming.document_type, visible_to_resident=True
            ),
            False,
        )

        # Date filter: letter date vs received
        qs = filter_correspondence(
            Document.objects.all(),
            date_from="2026-11-19",
            date_to="2026-11-19",
            date_field="letter",
        )
        self.assertIn(incoming, list(qs))
        qs_recv = filter_correspondence(
            Document.objects.all(),
            date_from="2026-11-21",
            date_to="2026-11-21",
            date_field="received",
        )
        self.assertIn(incoming, list(qs_recv))
        qs_wrong = filter_correspondence(
            Document.objects.all(),
            date_from="2026-11-19",
            date_to="2026-11-19",
            date_field="received",
        )
        self.assertNotIn(incoming, list(qs_wrong))

        # Prepare reply
        detail = reverse("erp:correspondence_detail", kwargs={"pk": incoming.pk})
        r = self.client.post(
            detail,
            {
                "action": "prepare_reply",
                "title": "Cavab: icarə uzadılması",
                "submit_token": "reply1",
                "file": _pdf("reply-v1.pdf", b"%PDF-1.4 v1"),
            },
        )
        self.assertEqual(r.status_code, 302)
        reply = Document.objects.get(direction=CorrespondenceDirection.OUTGOING)
        self.assertEqual(reply.related_correspondence_id, incoming.pk)
        self.assertTrue(reply.registry_number.startswith("OUT-"))

        # Submit v1 for approval
        reply_url = reverse("erp:correspondence_detail", kwargs={"pk": reply.pk})
        self.client.post(
            reply_url,
            {"action": "submit_approval", "submit_token": "apr1"},
        )
        # During review: upload v2 (supersedes pending)
        self.client.post(
            reply_url,
            {
                "action": "add_version",
                "submit_token": "ver2",
                "file": _pdf("reply-v2.pdf", b"%PDF-1.4 v2 approved"),
            },
        )
        reply.refresh_from_db()
        self.assertEqual(reply.versions.count(), 2)
        DocumentService.submit_for_approval(reply, actor=self.fm)

        # Management approves current (v2) — ApprovalRequest.entity is DocumentVersion
        req = DocumentService.pending_approval_for_document(reply)
        self.assertIsNotNone(req)
        DocumentService.decide_approval(req, actor=self.mgmt, approved=True, comment="OK")
        approved = _approved_version_for(reply)
        self.assertIsNotNone(approved)
        self.assertEqual(approved.version_label, "2")

        # Dispatch approved version
        r = self.client.post(
            reply_url,
            {
                "action": "dispatch",
                "recipient": "ASBC Demo",
                "channel": "manual",
                "operation_key": f"disp-{reply.pk}-{approved.pk}",
                "submit_token": "disp1",
            },
        )
        self.assertEqual(r.status_code, 302)
        # Repeat dispatch — one record
        self.client.post(
            reply_url,
            {
                "action": "dispatch",
                "recipient": "ASBC Demo",
                "channel": "manual",
                "operation_key": f"disp-{reply.pk}-{approved.pk}",
                "submit_token": "disp2",
            },
        )
        self.assertEqual(DocumentDispatch.objects.filter(document=reply).count(), 1)
        dispatch = DocumentDispatch.objects.get(document=reply)
        self.assertEqual(dispatch.version_id, approved.pk)

        # Later draft v3 — historical dispatched version still retrievable
        DocumentService.add_version(
            reply, uploaded_file=_pdf("reply-v3.pdf", b"%PDF-1.4 draft"), created_by=self.fm
        )
        reply.refresh_from_db()
        self.assertEqual(reply.versions.filter(is_current=True).count(), 1)
        self.assertNotEqual(reply.versions.get(is_current=True).pk, approved.pk)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.version_id, approved.pk)
        self.assertTrue(dispatch.version.file)

        # Download approved/dispatched version
        r = self.client.get(
            reverse("erp:document_download", kwargs={"pk": reply.pk}),
            {"version": str(approved.pk)},
        )
        self.assertEqual(r.status_code, 200)

        # Pairing another document's version ID must 404
        r = self.client.get(
            reverse("erp:document_download", kwargs={"pk": incoming.pk}),
            {"version": str(approved.pk)},
        )
        self.assertEqual(r.status_code, 404)

        # Linking company does not publish to portal
        self.assertFalse(reply.visible_to_resident)
        self.assertFalse(user_can_download_document(self.sales, reply))

        # Registry search by internal + external
        list_r = self.client.get(
            reverse("erp:correspondence_list"),
            {"registry": reply.registry_number, "external_ref": "ASBC-LET"},
        )
        self.assertEqual(list_r.status_code, 200)
        self.assertContains(list_r, reply.registry_number)
        self.assertContains(list_r, incoming.registry_number)

        # Bidirectional navigation
        r = self.client.get(reverse("erp:correspondence_detail", kwargs={"pk": reply.pk}))
        self.assertContains(r, incoming.registry_number)
        r = self.client.get(reverse("erp:correspondence_detail", kwargs={"pk": incoming.pk}))
        self.assertContains(r, reply.registry_number)

    def test_sales_cannot_register_direct(self):
        self.client.force_login(self.sales)
        r = self.client.post(
            reverse("erp:correspondence_list"),
            {
                "action": "register_incoming",
                "title": "Hack",
                "submit_token": "x",
                "file": _pdf("x.pdf"),
            },
        )
        self.assertIn(r.status_code, (302, 403))
        self.assertFalse(
            Document.objects.filter(document_type__code=DOCUMENT_TYPE_INCOMING_LETTER).exists()
        )


class Phase10RegistryNumberConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_rbac_catalog()

    def test_concurrent_allocate_unique(self):
        barrier = Barrier(2)
        results = []

        def worker():
            barrier.wait()
            try:
                results.append(
                    allocate_registry_number(direction=CorrespondenceDirection.INCOMING)
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(worker), pool.submit(worker)]
            for f in futs:
                f.result()
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 2)
