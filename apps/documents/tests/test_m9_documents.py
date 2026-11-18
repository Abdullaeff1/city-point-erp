from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.documents.access import sensitivity_for_new_document, user_can_download_document
from apps.documents.models import (
    DEFAULT_RETENTION_DAYS,
    Document,
    DocumentSensitivity,
    DocumentType,
    DOCUMENT_TYPE_LEASE_CONTRACT,
    DOCUMENT_TYPE_OTHER,
)
from apps.documents.services import DocumentService
from apps.residents.models import ResidentCompany

User = get_user_model()


class DocumentSensitivityAclTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(name="M9 Co", slug="m9-co", portal_active=True)
        self.admin = User.objects.create_user(
            username="m9-admin", email="m9-admin@test.az", password="Pass12345!", role=Role.ADMIN
        )
        self.reception = User.objects.create_user(
            username="m9-rec", email="m9-rec@test.az", password="Pass12345!", role=Role.RECEPTION
        )
        self.accountant = User.objects.create_user(
            username="m9-acc", email="m9-acc@test.az", password="Pass12345!", role=Role.ACCOUNTANT
        )
        self.dtype, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_LEASE_CONTRACT,
            defaults={
                "name": "İcarə müqaviləsi",
                "default_sensitivity": DocumentSensitivity.CONFIDENTIAL,
                "retention_days": DEFAULT_RETENTION_DAYS[DOCUMENT_TYPE_LEASE_CONTRACT],
            },
        )
        self.dtype.default_sensitivity = DocumentSensitivity.CONFIDENTIAL
        self.dtype.retention_days = DEFAULT_RETENTION_DAYS[DOCUMENT_TYPE_LEASE_CONTRACT]
        self.dtype.save(update_fields=["default_sensitivity", "retention_days"])

    def test_upload_sets_sensitivity_and_meta(self):
        uploaded = SimpleUploadedFile("lease.pdf", b"%PDF-1.4 m9", content_type="application/pdf")
        doc = DocumentService.upload_new(
            title="Müqavilə M9",
            uploaded_file=uploaded,
            company=self.company,
            document_type=self.dtype,
            created_by=self.admin,
        )
        self.assertEqual(doc.sensitivity, DocumentSensitivity.CONFIDENTIAL)
        self.assertEqual(doc.content_type, "application/pdf")
        self.assertTrue(doc.size_bytes and doc.size_bytes > 0)
        self.assertTrue(doc.versions.filter(is_current=True).exists())

    def test_visible_to_resident_forces_public_sensitivity(self):
        self.assertEqual(
            sensitivity_for_new_document(document_type=self.dtype, visible_to_resident=True),
            DocumentSensitivity.PUBLIC_RESIDENT,
        )

    def test_download_acl_by_sensitivity(self):
        doc = Document.objects.create(
            title="Conf",
            published_at=timezone.localdate(),
            company=self.company,
            sensitivity=DocumentSensitivity.CONFIDENTIAL,
            document_type=self.dtype,
        )
        self.assertTrue(user_can_download_document(self.admin, doc))
        self.assertTrue(user_can_download_document(self.accountant, doc))
        self.assertFalse(user_can_download_document(self.reception, doc))

        doc.sensitivity = DocumentSensitivity.RESTRICTED
        doc.save(update_fields=["sensitivity"])
        self.assertTrue(user_can_download_document(self.accountant, doc))
        self.assertFalse(user_can_download_document(self.reception, doc))


class PurgeExpiredDocumentsTests(TestCase):
    def setUp(self):
        self.dtype, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_OTHER,
            defaults={"name": "Digər", "retention_days": 30},
        )
        self.dtype.retention_days = 30
        self.dtype.save(update_fields=["retention_days"])
        old = timezone.localdate() - timedelta(days=60)
        self.doc = Document.objects.create(
            title="Old other",
            published_at=old,
            document_date=old,
            document_type=self.dtype,
            sensitivity=DocumentSensitivity.INTERNAL,
        )
        self.doc.file.save("old.txt", SimpleUploadedFile("old.txt", b"x"), save=True)

    def test_purge_dry_run_then_apply(self):
        out = StringIO()
        call_command("purge_expired_documents", stdout=out)
        self.assertIn("expired_candidates=1", out.getvalue())
        self.assertTrue(Document.objects.filter(pk=self.doc.pk).exists())
        call_command("purge_expired_documents", "--apply", stdout=StringIO())
        self.assertFalse(Document.objects.filter(pk=self.doc.pk).exists())
