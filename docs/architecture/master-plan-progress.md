# Master plan execution status (Phases 0–13)

Updated: 2026-09-21

This documents what was **implemented in code** vs what remains **ops/business-gated**.  
Scaffold UI alone ≠ Definition of Done.

| Phase | Status | What landed in code |
|-------|--------|---------------------|
| **0 Audit** | Done | 10 audit artifacts under `docs/` |
| **1 Hardening** | Code done / ops open | portal_active, announcement scopes, CP_ENV, SMTP log, AxTrax health, poller task script, pilot checklist |
| **2 ERP Core** | Done (foundation) | Domain events→audit, Organization tree, ApprovalService, Party dual-read, email helper |
| **3 Property/Lease** | Thin-real | Space rates/availability/fit-out; lease `billing_frequency`; `LeaseService.create_draft`; monthly charge generator |
| **4 CRM + Website** | Thin-real | `CrmService` qualify/opportunity/offer→lease; ERP POST actions; public API optional `PUBLIC_API_KEY` + rates on spaces |
| **5 Resident/Access** | Thin-real | `card_order_status` workflow field; portal guest history (`?days=`); AxTrax write still mock |
| **6 Service Desk** | Evolve | `WaitingReasonCode` + `waiting_reason_code`; existing routing/SLA preserved |
| **7 FM** | Thin-real | `WorkOrderService.set_status` + billable→Charge + `WORK_ORDER_CLOSED` event; ERP POST |
| **8 Warehouse** | Thin-real | Negative stock guard; low-stock → create PR from ERP |
| **9 Procurement** | Thin-real | PR approve → PO → receive→stock; ApprovalService + events |
| **10 DMS** | Thin-real | `DocumentService.upload_new` / `add_version` |
| **11 Billing** | Thin-real | Monthly lease charges; invoice+due; `Payment`; invoice→journal hook |
| **12 Accounting** | Thin-real | Minimal CoA seed; `post_journal`; invoice AR/revenue JE |
| **13 BI** | Partial | Existing KPI reports remain; data will improve as workflows used |

## Honest limits

- Full multi-screen UX for every module is **not** complete.
- AxTrax **write** not invented (adapter mock).
- SLA durations / taxonomy final matrix need City Point business approval.
- Party/Person cutover not finished (dual-read only).
- RFQ comparison, PM auto-generation, portal invoices, full BI exports — deferred.

## Commands

```bash
python manage.py sync_parties
python manage.py generate_lease_charges
python manage.py axtrax_sync_status
python manage.py retry_invite_emails
```
