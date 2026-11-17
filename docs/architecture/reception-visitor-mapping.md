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

1. Walk-in / check-in with **ID held**: **seriya nömrəsi** + qonaq kartı tələb olunur.
2. ID held **deyil**: `reception.override_id` + səbəb. **İstisnalar:** `visit_type=courier`, guest-list import check-in (siyahı).
3. Host must belong to selected company and be **active** (portal pre-reg daxil).
4. One active `inside` visit per guest at a time (block duplicate check-in).
5. Check-out requires ID return unless `return_pending` override.
6. Cancelled visits cannot check in; `no_show` requires `reception.cancel_visit`.
7. Seriya nömrəsi masked in UI unless `reception.view_sensitive_data`.
8. Turnstile sync failure must not block reception registration.

**M5:** [m5-portal-reception-employees.md](m5-portal-reception-employees.md).

## Permissions

`reception.view`, `create_visit`, `check_in`, `check_out`, `cancel_visit`, `search`, `export`, `view_sensitive_data`, `override_id`
