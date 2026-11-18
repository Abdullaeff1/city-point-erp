# M9 — Sənədlər və Bildirişlər

**Status:** icra olunub (2026-11-18)  
**Defer:** Outlook/Zoho yalnız şəbəkə qərarı təsdiqləndikdən sonra; retention hüquqi UAT təsdiqi

---

## 1. Sənəd məxfiliyi

| Maddə | Kod |
|-------|-----|
| Vahid sensitivity | `DocumentSensitivity` + `Document.sensitivity` / `DocumentType.default_sensitivity` |
| Upload meta | `content_type`, `size_bytes`, versiya, `created_by` |
| Download ACL | `documents.access.user_can_download_document` (ERP + portal) |
| Private storage | `private_document_storage` (Document + AnnouncementAttachment) |
| Retention scaffold | `DEFAULT_RETENTION_DAYS` + `purge_expired_documents` |

---

## 2. Bildirişlər

| Maddə | Kod |
|-------|-----|
| In-app ↔ domain event | `event_handlers` → `notify_in_app` (ticket/WO/approval) |
| Email outbox | `NotificationDispatch` + `flush_pending_email_dispatches` |
| Retry | `attempt_count`, `next_retry_at`, `requeue_failed_email_dispatches` |
| Offline invite | `CP_OFFLINE=1` → SMTP fail raise etmir; URL outbox-da qalır |

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M9-1 | Sensitivity + upload meta | test |
| M9-2 | Download ACL by role | test |
| M9-3 | Outbox retry ladder | test |
| M9-4 | Offline invite no-raise | test |
| M9-5 | Domain event → in-app | test |
| M9-6 | Retention purge dry-run/apply | test |

UAT hüquqi retention + Zoho/Outlook şəbəkə qərarı ayrıca.
