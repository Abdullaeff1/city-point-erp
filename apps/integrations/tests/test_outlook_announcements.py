from django.test import TestCase

from apps.comms.models import (
    Announcement,
    AnnouncementAttachment,
    AnnouncementSource,
    AnnouncementVisibility,
)
from apps.integrations.outlook_announcements import (
    OutlookConfig,
    ingest_graph_message,
    sync_outlook_announcements,
)


class FakeGraphClient:
    """Minimal stand-in for GraphMailClient used by ingest/sync."""

    def __init__(self, messages, attachments_by_message=None, files_by_attachment=None):
        self._messages = messages
        self._attachments = attachments_by_message or {}
        self._files = files_by_attachment or {}
        self.config = OutlookConfig(
            tenant_id="t",
            client_id="c",
            client_secret="s",
            mailbox="erp-announcements@example.com",
        )

    def list_inbox_messages(self, *, top: int = 25):
        return self._messages[:top]

    def list_attachments(self, message_id: str):
        return list(self._attachments.get(message_id) or [])

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self._files.get((message_id, attachment_id), b"")


class OutlookAnnouncementSyncTests(TestCase):
    def test_create_building_announcement_with_pdf_attachment(self):
        message = {
            "id": "msg-1",
            "internetMessageId": "<lift-repair@citypoint.az>",
            "subject": "Lift təmiri",
            "body": {"contentType": "html", "content": "<p>Bu gün <b>A</b> liftində iş.</p>"},
            "receivedDateTime": "2026-10-29T10:15:00Z",
            "hasAttachments": True,
        }
        client = FakeGraphClient(
            messages=[message],
            attachments_by_message={
                "msg-1": [
                    {
                        "id": "att-1",
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": "plan.pdf",
                        "contentType": "application/pdf",
                        "size": 12_000,
                        "isInline": False,
                    },
                    {
                        "id": "att-logo",
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": "logo.png",
                        "contentType": "image/png",
                        "size": 800,
                        "isInline": True,
                        "contentId": "cid:logo",
                    },
                ]
            },
            files_by_attachment={
                ("msg-1", "att-1"): b"%PDF-1.4 fake",
                ("msg-1", "att-logo"): b"\x89PNG",
            },
        )

        stats = sync_outlook_announcements(client=client, top=10)
        self.assertEqual(stats["fetched"], 1)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["skipped"], 0)

        ann = Announcement.objects.get(external_message_id="<lift-repair@citypoint.az>")
        self.assertEqual(ann.title, "Lift təmiri")
        self.assertIn("A", ann.body)
        self.assertNotIn("<b>", ann.body)
        self.assertEqual(ann.visibility, AnnouncementVisibility.BUILDING)
        self.assertEqual(ann.source, AnnouncementSource.OUTLOOK)
        self.assertEqual(ann.severity, "important")

        attachments = list(ann.attachments.all())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].title, "plan.pdf")
        self.assertIn("plan", attachments[0].file.name.lower())
        self.assertTrue(attachments[0].file.size > 0)

    def test_dedup_second_poll_skips_and_keeps_single_attachment(self):
        message = {
            "id": "msg-2",
            "internetMessageId": "<unique-mail-id@citypoint.az>",
            "subject": "Parkinq",
            "body": {"contentType": "text", "content": "B2 yenilənir"},
            "receivedDateTime": "2026-10-28T08:00:00Z",
            "hasAttachments": True,
        }
        client = FakeGraphClient(
            messages=[message],
            attachments_by_message={
                "msg-2": [
                    {
                        "id": "a1",
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": "map.pdf",
                        "contentType": "application/pdf",
                        "size": 5000,
                        "isInline": False,
                    }
                ]
            },
            files_by_attachment={("msg-2", "a1"): b"%PDF map"},
        )

        first = sync_outlook_announcements(client=client)
        second = sync_outlook_announcements(client=client)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(Announcement.objects.filter(external_message_id="<unique-mail-id@citypoint.az>").count(), 1)
        self.assertEqual(AnnouncementAttachment.objects.count(), 1)

    def test_unconfigured_env_is_noop(self):
        stats = sync_outlook_announcements(client=None)
        self.assertEqual(stats["fetched"], 0)
        self.assertEqual(Announcement.objects.count(), 0)

    def test_ingest_without_attachments_flag(self):
        message = {
            "id": "msg-3",
            "internetMessageId": "<no-files@citypoint.az>",
            "subject": "Info",
            "body": {"contentType": "text", "content": "Sadə mətn"},
            "receivedDateTime": "2026-10-27T12:00:00Z",
            "hasAttachments": False,
        }
        ann, status = ingest_graph_message(message, client=None, fetch_attachments=False)
        self.assertEqual(status, "created")
        self.assertIsNotNone(ann)
        self.assertEqual(ann.attachments.count(), 0)
