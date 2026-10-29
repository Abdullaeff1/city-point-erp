"""Microsoft Graph → portal Announcement sync (shared mailbox inbox).

Staff BCC CC-Office → shared mailbox member → poller creates BUILDING announcements
with file attachments. Credentials via OUTLOOK_* env vars; missing config = no-op.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.comms.models import (
    Announcement,
    AnnouncementAttachment,
    AnnouncementSeverity,
    AnnouncementSource,
    AnnouncementVisibility,
)

logger = logging.getLogger(__name__)

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Skip tiny inline images / signatures (bytes)
MIN_ATTACHMENT_BYTES = 2_048
# Skip common inline image types when contentId is set (embedded in HTML body)
INLINE_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/bmp",
}


@dataclass
class OutlookConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox: str

    @classmethod
    def from_env(cls) -> OutlookConfig | None:
        tenant = (os.environ.get("OUTLOOK_TENANT_ID") or "").strip()
        client_id = (os.environ.get("OUTLOOK_CLIENT_ID") or "").strip()
        secret = (os.environ.get("OUTLOOK_CLIENT_SECRET") or "").strip()
        mailbox = (os.environ.get("OUTLOOK_MAILBOX") or "").strip()
        if not all([tenant, client_id, secret, mailbox]):
            return None
        return cls(
            tenant_id=tenant,
            client_id=client_id,
            client_secret=secret,
            mailbox=mailbox,
        )


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    text = strip_tags(value)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_received(value: str | None):
    if not value:
        return timezone.localdate()
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, ZoneInfo("UTC"))
        return timezone.localtime(dt).date()
    except (TypeError, ValueError):
        return timezone.localdate()


def _should_skip_attachment(meta: dict[str, Any]) -> bool:
    if meta.get("isInline") and (meta.get("contentType") or "").lower() in INLINE_IMAGE_TYPES:
        return True
    size = int(meta.get("size") or 0)
    if size and size < MIN_ATTACHMENT_BYTES and (meta.get("contentType") or "").lower().startswith(
        "image/"
    ):
        return True
    if meta.get("contentId") and (meta.get("contentType") or "").lower() in INLINE_IMAGE_TYPES:
        return True
    name = (meta.get("name") or "").strip()
    if not name:
        return True
    return False


class GraphMailClient:
    """Thin Graph client; injectable for tests via fetch_* overrides / monkeypatch."""

    def __init__(self, config: OutlookConfig, *, http_client=None, token_provider=None):
        self.config = config
        self._http = http_client
        self._token_provider = token_provider
        self._token: str | None = None

    def _ensure_http(self):
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=60.0)
        return self._http

    def acquire_token(self) -> str:
        if self._token_provider:
            self._token = self._token_provider()
            return self._token
        import msal

        app = msal.ConfidentialClientApplication(
            self.config.client_id,
            authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            client_credential=self.config.client_secret,
        )
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(
                result.get("error_description")
                or result.get("error")
                or "Graph token acquire failed"
            )
        self._token = result["access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        token = self._token or self.acquire_token()
        return {"Authorization": f"Bearer {token}"}

    def list_inbox_messages(self, *, top: int = 25) -> list[dict[str, Any]]:
        http = self._ensure_http()
        mailbox = self.config.mailbox
        url = (
            f"{GRAPH_BASE}/users/{mailbox}/mailFolders/inbox/messages"
            f"?$top={top}"
            f"&$orderby=receivedDateTime desc"
            f"&$select=id,subject,body,bodyPreview,receivedDateTime,internetMessageId,hasAttachments"
        )
        resp = http.get(url, headers=self._headers())
        resp.raise_for_status()
        return list(resp.json().get("value") or [])

    def list_attachments(self, message_id: str) -> list[dict[str, Any]]:
        http = self._ensure_http()
        mailbox = self.config.mailbox
        url = (
            f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/attachments"
            f"?$select=id,name,contentType,size,isInline,contentId"
        )
        resp = http.get(url, headers=self._headers())
        resp.raise_for_status()
        return list(resp.json().get("value") or [])

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        http = self._ensure_http()
        mailbox = self.config.mailbox
        url = (
            f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}"
            f"/attachments/{attachment_id}/$value"
        )
        resp = http.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.content


def _message_body_text(message: dict[str, Any]) -> str:
    body = message.get("body") or {}
    content = body.get("content") or ""
    content_type = (body.get("contentType") or "").lower()
    if content_type == "html":
        return _html_to_text(content)
    text = (content or message.get("bodyPreview") or "").strip()
    return text


def _safe_filename(name: str) -> str:
    base = os.path.basename(name).strip() or "attachment"
    return re.sub(r"[^\w.\- ()\[\]]+", "_", base)[:180]


@transaction.atomic
def ingest_graph_message(
    message: dict[str, Any],
    *,
    client: GraphMailClient | None = None,
    fetch_attachments: bool = True,
) -> tuple[Announcement | None, str]:
    """
    Create BUILDING announcement from one Graph message dict.
    Returns (announcement_or_None, status) where status is created|skipped|error.
    """
    external_id = (message.get("internetMessageId") or message.get("id") or "").strip()
    if not external_id:
        return None, "skipped"

    existing = Announcement.objects.filter(external_message_id=external_id).first()
    if existing:
        return existing, "skipped"

    title = (message.get("subject") or "").strip() or "(mövzusuz)"
    title = title[:200]
    body = _message_body_text(message) or title
    published = _parse_received(message.get("receivedDateTime"))

    ann = Announcement.objects.create(
        title=title,
        body=body,
        severity=AnnouncementSeverity.IMPORTANT,
        published_at=published,
        visibility=AnnouncementVisibility.BUILDING,
        source=AnnouncementSource.OUTLOOK,
        external_message_id=external_id,
    )

    graph_id = (message.get("id") or "").strip()
    if fetch_attachments and client and message.get("hasAttachments") and graph_id:
        try:
            for meta in client.list_attachments(graph_id):
                if (meta.get("@odata.type") or "").endswith("itemAttachment"):
                    continue
                if _should_skip_attachment(meta):
                    continue
                att_id = meta.get("id")
                if not att_id:
                    continue
                raw = client.download_attachment(graph_id, att_id)
                if not raw:
                    continue
                filename = _safe_filename(meta.get("name") or "file")
                attachment = AnnouncementAttachment(announcement=ann, title=filename)
                attachment.file.save(filename, ContentFile(raw), save=True)
        except Exception:  # noqa: BLE001
            logger.exception("Outlook attachment sync failed for %s", external_id)

    return ann, "created"


def sync_outlook_announcements(
    *,
    client: GraphMailClient | None = None,
    top: int = 25,
) -> dict[str, int]:
    """
    Pull recent inbox messages and upsert BUILDING announcements.
    When client is None, builds from env; missing env returns zeros (no-op).
    """
    stats = {"fetched": 0, "created": 0, "skipped": 0, "errors": 0}
    if client is None:
        config = OutlookConfig.from_env()
        if config is None:
            logger.info("Outlook announcements sync skipped: OUTLOOK_* env not configured")
            return stats
        client = GraphMailClient(config)

    try:
        messages = client.list_inbox_messages(top=top)
    except Exception:  # noqa: BLE001
        logger.exception("Outlook inbox list failed")
        stats["errors"] += 1
        return stats

    stats["fetched"] = len(messages)
    for message in messages:
        try:
            _, status = ingest_graph_message(message, client=client, fetch_attachments=True)
            if status == "created":
                stats["created"] += 1
            else:
                stats["skipped"] += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "Outlook message ingest failed id=%s",
                message.get("internetMessageId") or message.get("id"),
            )
            stats["errors"] += 1
    return stats
