# Zoho Mail → Portal elanları (A.8)

`all residents` (və ya konfiq siyahısı) ünvanına göndərilən Zoho Mail məktubları ERP-də **bina-ümumi** (`visibility=building`, `source=zoho`) `Announcement` olur. Dedup: `Message-ID` → `external_message_id`.

Outlook Graph poller **legacy** qalır; yeni quraşdırmalar Zoho istifadə etməlidir.

## Axın

1. Staff → Zoho → To/Cc `all residents` qrupu
2. Poll mailbox (IMAP) məktubu oxuyur
3. `poll_zoho_announcements` bina elanı yaradır
4. Portal → Elanlar (bütün şirkətlər)

## ERP `.env`

```bash
ZOHO_POLL_ON_START=1
ZOHO_POLL_INTERVAL=60
ZOHO_IMAP_HOST=imap.zoho.com
ZOHO_IMAP_PORT=993
ZOHO_IMAP_USER=erp-announcements@citypoint.az
ZOHO_IMAP_PASSWORD=...
ZOHO_IMAP_MAILBOX=INBOX
ZOHO_ALL_RESIDENTS_ADDRESS=all.residents@citypoint.az
# Optional: ZOHO_SENDER_ALLOWLIST=ops@citypoint.az,fm@citypoint.az
```

Bir dəfəlik:

```bash
python manage.py poll_zoho_announcements --once
```
