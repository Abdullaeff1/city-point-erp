# Phase 0.10 — Recommended Implementation Order

Aligned with Final Master Plan §28. Blocking dependencies respected.

```text
Phase 0  Audit          ← COMPLETE (this document set)
   ↓
Phase 1  Production Hardening     ← NEXT
   ↓
Phase 2  ERP Core (Party link incremental, RBAC, notify, audit, events)
   ↓
Phase 3  Property / Space / Lease (+ billing foundation fields)
   ↓
Phase 4  CRM + Website
   ↓
Phase 5  Resident / Reception / Access completion (no AxTrax invent-write)
   ↓
Phase 6  Service Desk evolve (no rewrite)
   ↓
Phase 7  Facility Management
   ↓
Phase 8  Warehouse
   ↓
Phase 9  Procurement
   ↓
Phase 10 DMS / Kargüzarlıq
   ↓
Phase 11 Billing
   ↓
Phase 12 Accounting
   ↓
Phase 13 Management / BI
   ↓
Production Acceptance (all 7 flows)
```

## Phase 1 immediate backlog (ordered)

1. Enforce `portal_active` on portal access
2. Announcement visibility scopes (building / company / targeted)
3. Production: `SEED_DEMO=0`, no demo passwords in prod entrypoint; secret fail-closed
4. SMTP + delivery logging path (at least invite/reset)
5. AxTrax poller reliability: scheduled task doc + SyncLog health surface in admin/ERP
6. Backup/restore procedure docs + verification checklist
7. Tighten password-reset user queryset policy
8. Nav/docs: label scaffold modules as foundation (optional UI hide for non-admin)

## Preserve during all phases

Reception, Ticket mechanics, Security portal, AxTrax **read** path — extend only.

## Stop conditions

Do not start Phase 3+ commercial depth until Phase 1 pilot DoD met (1–2 real companies, critical flows without critical defects).
