# M6 — Service Desk və Ticket

**Status:** icra olunub (2026-11-17)  
**Defer:** warehouse material e2e (Phase 7–8), Party cutover

---

## 1. Mövcud (işlək)

Portal/ERP create → `route_ticket` → dept ACL → status/SLA/waiting → əl ilə WO (`create_wo_from_ticket`).  
C4 minimum: create → assign → optional WO.

---

## 2. M6 düzəlişləri

| Maddə | Nəticə |
|-------|--------|
| TD-08 email outbox | `flush_pending_email_dispatches` + `flush_email_outbox` / `poll_email_outbox` |
| Company notify | membership ∪ `resident_company` |
| Portal delete scope | `company_ids` session scope |
| Ticket email subject | payload.subject (AZ) |
| ACL doc | handoff = tutan şöbə + Admin/Management |

Poller flag: `TICKET_EMAIL_OUTBOX_POLL_ON_START=1` (default off).

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M6-1 | Outbox flush | test + command |
| M6-2 | Membership notify | test |
| M6-3 | Portal delete scope | test |
| M6-4 | Doc sync | `tickets-department-access.md` |
| M6-5 | C4 | create→assign→WO; WH deferred |

UAT §C operator Pass ayrıca.
