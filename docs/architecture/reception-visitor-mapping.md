# Reception — Legacy mapping & business rules

**Date:** 2026-09-16  
**Scope:** Visitor Management (Excel replacement)

## Legacy → New

| Legacy | New |
|--------|-----|
| `Guest.full_name` | `first_name` + `last_name` (split on first space; keep `full_name` property) |
| — | `Guest.fin_code` — **şəxsiyyət vəsiqəsi seriya №** (DB field name legacy; indexed, normalized alphanumeric) |
| `GuestVisit.status` waiting/inside/left/… | + `no_show`, `return_pending` |
| — | `VisitorType` FK |
| — | `id_document_held`, `id_document_returned_at`, `document_note` |
| — | `VisitorAccess` (turnstile foundation, mock only) |
| `invite_code` | unchanged (visit code) |
| `ResidentCompany` FK | remains SoT for visit company (Party dual-write elsewhere) |

## Business rules

1. Walk-in requires **seriya nömrəsi**, first/last name, company, ID held=True (override needs permission + reason).
2. Host must belong to selected company.
3. One active `inside` visit per guest at a time (block duplicate check-in).
4. Check-out requires ID return unless `return_pending` override.
5. Cancelled visits cannot check in.
6. Seriya nömrəsi masked in UI unless `reception.view_sensitive_data`.
7. Turnstile sync failure must not block reception registration.

## Permissions

`reception.view`, `create_visit`, `check_in`, `check_out`, `cancel_visit`, `search`, `export`, `view_sensitive_data`, `override_id`
