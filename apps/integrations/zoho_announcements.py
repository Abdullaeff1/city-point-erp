"""Zoho Mail IMAP → portal Announcement sync (all-residents → BUILDING).

Mails addressed to the configured «all residents» group become building-wide
announcements. Credentials via ZOHO_* env; missing config = no-op.
Outlook Graph poller remains as legacy.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import html
import imaplib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.comms.models import (
    Announcement,
    AnnouncementSeverity,
    AnnouncementSource,
    AnnouncementVisibility,
)

logger = logging.getLogger(__name__)


def _split_addrs(raw: str) -> list[str]:
    return [p.strip().lower() for p in (raw or "").split(",") if p.strip()]


@dataclass
class ZohoConfig:
    imap_host: str
    imap_port: int
    username: str
    password: str
    all_residents_addresses: list[str]
    sender_allowlist: list[str] = field(default_factory=list)
    mailbox: str = "INBOX"
    use_ssl: bool = True

    @classmethod
    def from_env(cls) -> ZohoConfig | None:
        user = (os.environ.get("ZOHO_IMAP_USER") or "").strip()
        password = (os.environ.get("ZOHO_IMAP_PASSWORD") or "").strip()
        addresses = _split_addrs(os.environ.get("ZOHO_ALL_RESIDENTS_ADDRESS") or "")
        if not user or not password or not addresses:
            return None
        host = (os.environ.get("ZOHO_IMAP_HOST") or "imap.zoho.com").strip()
        port = int(os.environ.get("ZOHO_IMAP_PORT") or "993")
        allowlist = _split_addrs(os.environ.get("ZOHO_SENDER_ALLOWLIST") or "")
        mailbox = (os.environ.get("ZOHO_IMAP_MAILBOX") or "INBOX").strip() or "INBOX"
        return cls(
            imap_host=host,
            imap_port=port,
            username=user,
            password=password,
            all_residents_addresses=addresses,
            sender_allowlist=allowlist,
            mailbox=mailbox,
            use_ssl=os.environ.get("ZOHO_IMAP_SSL", "1") != "0",
        )


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    text = strip_tags(value)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_date(value: str | None | datetime):
    if isinstance(value, datetime):
        dt = value
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, ZoneInfo("UTC"))
        return timezone.localtime(dt).date()
    if not value:
        return timezone.localdate()
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, ZoneInfo("UTC"))
        return timezone.localtime(dt).date()
    except (TypeError, ValueError, IndexError):
        return timezone.localdate()


def _addrs_from_header(msg: Message, *headers: str) -> list[str]:
    out: list[str] = []
    for header in headers:
        raw = msg.get(header) or ""
        for _, addr in email.utils.getaddresses([raw]):
            if addr:
                out.append(addr.strip().lower())
    return out


def _body_from_message(msg: Message) -> str:
    if msg.is_multipart():
        plain = ""
        html_part = ""
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get_content_disposition() or "").lower()
            if disp == "attachment":
                continue
            try:
                payload = part.get_content()
            except Exception:  # noqa: BLE001
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    payload = payload.decode(charset, errors="replace")
            if not isinstance(payload, str):
                continue
            if ctype == "text/plain" and not plain:
                plain = payload
            elif ctype == "text/html" and not html_part:
                html_part = payload
        if plain.strip():
            return plain.strip()
        if html_part:
            return _html_to_text(html_part)
        return ""
    try:
        content = msg.get_content()
    except Exception:  # noqa: BLE001
        raw = msg.get_payload(decode=True)
        if isinstance(raw, bytes):
            content = raw.decode(msg.get_content_charset() or "utf-8", errors="replace")
        else:
            content = str(msg.get_payload() or "")
    ctype = (msg.get_content_type() or "").lower()
    if ctype == "text/html":
        return _html_to_text(content)
    return (content or "").strip()


def message_dict_from_email(msg: Message) -> dict[str, Any]:
    message_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    subject = (msg.get("Subject") or "").strip() or "(mövzusuz)"
    return {
        "message_id": message_id,
        "subject": subject[:200],
        "body": _body_from_message(msg) or subject,
        "date": msg.get("Date"),
        "to_addrs": _addrs_from_header(msg, "To", "Cc", "Delivered-To", "X-Original-To"),
        "from_addrs": _addrs_from_header(msg, "From"),
    }


def is_all_residents_message(
    message: dict[str, Any],
    *,
    all_residents_addresses: Iterable[str],
    sender_allowlist: Iterable[str] | None = None,
) -> bool:
    targets = {a.lower() for a in all_residents_addresses if a}
    recipients = {a.lower() for a in (message.get("to_addrs") or []) if a}
    if not targets.intersection(recipients):
        return False
    allow = [a.lower() for a in (sender_allowlist or []) if a]
    if allow:
        senders = {a.lower() for a in (message.get("from_addrs") or []) if a}
        if not senders.intersection(allow):
            return False
    return True


@transaction.atomic
def ingest_zoho_message(
    message: dict[str, Any],
    *,
    config: ZohoConfig | None = None,
) -> tuple[Announcement | None, str]:
    """
    Create BUILDING announcement from a normalized Zoho message dict.
    Returns (announcement_or_None, status) where status is created|skipped|error.
    """
    if config is not None and not is_all_residents_message(
        message,
        all_residents_addresses=config.all_residents_addresses,
        sender_allowlist=config.sender_allowlist,
    ):
        return None, "skipped"

    external_id = (message.get("message_id") or "").strip()
    if not external_id:
        return None, "skipped"

    existing = Announcement.objects.filter(external_message_id=external_id).first()
    if existing:
        return existing, "skipped"

    title = (message.get("subject") or "").strip() or "(mövzusuz)"
    title = title[:200]
    body = (message.get("body") or "").strip() or title
    published = _parse_date(message.get("date"))

    ann = Announcement.objects.create(
        title=title,
        body=body,
        severity=AnnouncementSeverity.IMPORTANT,
        published_at=published,
        visibility=AnnouncementVisibility.BUILDING,
        source=AnnouncementSource.ZOHO,
        external_message_id=external_id,
    )
    return ann, "created"


class ZohoImapClient:
    """Minimal IMAP client; injectable ``fetch_messages`` for tests."""

    def __init__(self, config: ZohoConfig):
        self.config = config

    def fetch_messages(self, *, limit: int = 25) -> list[dict[str, Any]]:
        if self.config.use_ssl:
            conn = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        else:
            conn = imaplib.IMAP4(self.config.imap_host, self.config.imap_port)
        try:
            conn.login(self.config.username, self.config.password)
            typ, _ = conn.select(self.config.mailbox, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"IMAP select failed: {self.config.mailbox}")
            typ, data = conn.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()
            ids = ids[-limit:] if limit else ids
            out: list[dict[str, Any]] = []
            for uid in reversed(ids):
                typ, msg_data = conn.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                out.append(message_dict_from_email(msg))
            return out
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass


def sync_zoho_announcements(
    *,
    client: ZohoImapClient | None = None,
    config: ZohoConfig | None = None,
    messages: list[dict[str, Any]] | None = None,
    limit: int = 25,
) -> dict[str, int]:
    """
    Pull recent Zoho inbox messages addressed to all-residents → BUILDING announcements.
    When client/config missing and messages not injected, builds from env; missing env = no-op.
    """
    stats = {"fetched": 0, "created": 0, "skipped": 0, "errors": 0}
    if config is None:
        config = ZohoConfig.from_env()
    if messages is None:
        if client is None:
            if config is None:
                logger.info("Zoho announcements sync skipped: ZOHO_* env not configured")
                return stats
            client = ZohoImapClient(config)
        try:
            messages = client.fetch_messages(limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("Zoho IMAP fetch failed")
            stats["errors"] += 1
            return stats

    if config is None:
        # Injected messages without config: treat all as candidates (tests pass allowlist via message)
        config = ZohoConfig(
            imap_host="",
            imap_port=993,
            username="",
            password="",
            all_residents_addresses=["all.residents@example.com"],
        )

    stats["fetched"] = len(messages)
    for message in messages:
        try:
            if not is_all_residents_message(
                message,
                all_residents_addresses=config.all_residents_addresses,
                sender_allowlist=config.sender_allowlist,
            ):
                stats["skipped"] += 1
                continue
            _, status = ingest_zoho_message(message, config=None)
            if status == "created":
                stats["created"] += 1
            else:
                stats["skipped"] += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "Zoho message ingest failed id=%s",
                message.get("message_id"),
            )
            stats["errors"] += 1
    return stats
