# Master plan execution status (Phases 0–13)

Updated: 2026-11-23

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
| **7 FM** | Productizing | WO status + billable→Charge; ERP PM plans UI (`/erp/maintenance/plans/`) + generate due WOs + inspection confirm on WO detail (2026-11) |
| **8 Warehouse** | Thin-real | Negative stock guard; low-stock → create PR from ERP |
| **9 Procurement** | Thin-real | PR approve → PO → receive→stock; ApprovalService + events |
| **10 DMS** | Thin-real | `DocumentService.upload_new` / `add_version` |
| **11 Billing** | Product DoD | Charge→invoice→payment; `invoice_balance`; portal `/portal/invoices/`; Finance `/finance/charges|invoices|payments`; Phase 11 A–G acceptance (2026-11) |
| **12 Accounting** | Product DoD | Synthetic 3-digit CoA; invoice/payment draft JE → accountant `post_to_gl`; period close; TB opening/movement/closing; Phase 12 A–C acceptance (2026-11) |
| **13 BI** | Product DoD | As-of occupancy/AR/WO/stock; operational vs posted AR; drill + multi-sheet Excel; Phase 13 acceptance (2026-11) |
| **Production Acceptance** | Local READY / on-site open | FSA 14 + full **791 OK** (2026-11-23); onsite sheet + AZ release report; deploy **BLOCKED** until Finance/NetAdmin/operator signatures |

## Honest limits

- Full multi-screen UX for every module is **not** complete.
- AxTrax **write** not invented (adapter mock).
- SLA durations / taxonomy final matrix need City Point business approval.
- Party/Person cutover not finished (dual-read only).
- Utilities tariff, unapplied overpayment credit, formal credit-note/correction policy, bank feed — Finance-pending (Phase 11/12).
- Procurement AP/payable JE (account 200 unused) — Finance owner; launch defer only with written decision.
- Website intake deferred without LAN/VPN path (Sales/IT).
- Full BI historical stock — current-only labeling (Phase 13).

## Commands

```bash
python manage.py sync_parties
python manage.py generate_lease_charges
python manage.py axtrax_sync_status
python manage.py retry_invite_emails
```
