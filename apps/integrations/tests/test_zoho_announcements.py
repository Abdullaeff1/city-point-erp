from django.test import TestCase

from apps.comms.models import Announcement, AnnouncementSource, AnnouncementVisibility
from apps.integrations.zoho_announcements import (
    ZohoConfig,
    ingest_zoho_message,
    sync_zoho_announcements,
)


class ZohoAnnouncementSyncTests(TestCase):
    def test_all_residents_creates_building_announcement(self):
        config = ZohoConfig(
            imap_host="imap.example.com",
            imap_port=993,
            username="u",
            password="p",
            all_residents_addresses=["all.residents@citypoint.az"],
        )
        message = {
            "message_id": "<lift-repair@zoho>",
            "subject": "Lift təmiri",
            "body": "Bu gün A liftində iş.",
            "date": "Wed, 12 Nov 2025 10:15:00 +0000",
            "to_addrs": ["all.residents@citypoint.az"],
            "from_addrs": ["ops@citypoint.az"],
        }
        stats = sync_zoho_announcements(config=config, messages=[message])
        self.assertEqual(stats["fetched"], 1)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["skipped"], 0)

        ann = Announcement.objects.get(external_message_id="<lift-repair@zoho>")
        self.assertEqual(ann.title, "Lift təmiri")
        self.assertEqual(ann.visibility, AnnouncementVisibility.BUILDING)
        self.assertEqual(ann.source, AnnouncementSource.ZOHO)
        self.assertIn("A liftində", ann.body)

    def test_non_all_residents_skipped(self):
        config = ZohoConfig(
            imap_host="imap.example.com",
            imap_port=993,
            username="u",
            password="p",
            all_residents_addresses=["all.residents@citypoint.az"],
        )
        message = {
            "message_id": "<private@zoho>",
            "subject": "Private",
            "body": "no",
            "date": None,
            "to_addrs": ["someone@example.com"],
            "from_addrs": ["ops@citypoint.az"],
        }
        stats = sync_zoho_announcements(config=config, messages=[message])
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["skipped"], 1)
        self.assertFalse(Announcement.objects.filter(external_message_id="<private@zoho>").exists())

    def test_dedup_second_poll(self):
        message = {
            "message_id": "<dup@zoho>",
            "subject": "Once",
            "body": "body",
            "date": None,
            "to_addrs": ["all.residents@citypoint.az"],
            "from_addrs": ["ops@citypoint.az"],
        }
        _, status1 = ingest_zoho_message(message)
        self.assertEqual(status1, "created")
        _, status2 = ingest_zoho_message(message)
        self.assertEqual(status2, "skipped")
        self.assertEqual(Announcement.objects.filter(external_message_id="<dup@zoho>").count(), 1)

    def test_sender_allowlist_blocks(self):
        config = ZohoConfig(
            imap_host="imap.example.com",
            imap_port=993,
            username="u",
            password="p",
            all_residents_addresses=["all.residents@citypoint.az"],
            sender_allowlist=["trusted@citypoint.az"],
        )
        message = {
            "message_id": "<spam@zoho>",
            "subject": "Spam",
            "body": "nope",
            "date": None,
            "to_addrs": ["all.residents@citypoint.az"],
            "from_addrs": ["random@example.com"],
        }
        stats = sync_zoho_announcements(config=config, messages=[message])
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["skipped"], 1)
