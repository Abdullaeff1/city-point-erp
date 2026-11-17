# Phase 0.9 — Business Gap Report

**Updated:** 2026-11-17. Compared to Final Master Plan e2e flows and module DoD.

| Flow / capability | Current | Gap |
|-------------------|---------|-----|
| **FLOW 1 New resident** Website→CRM→Lease→Portal→Access→Billing | CRM sales MVP + LeaseApplication→draft; activate cascade; billing charges | Public website API; accountant CoA/VAT UAT; Party cutover |
| **FLOW 2 Employee access** Employee→Credential→AxTrax→Event | Employee + card + read events; card order portal | Credential entity; AxTrax **write** (vendor) |
| **FLOW 3 Visitor** Portal→Reception→Access | Pre-reg + reception real | Temp AxTrax access mock |
| **FLOW 4 Technical ticket** Ticket→WO→Warehouse | Ticket+routing real; WO thin | Warehouse material consumption end-to-end |
| **FLOW 5 Commercial request** Ticket→CRM→Offer→Lease | CRM UI full path | Ticket→CRM handoff polish |
| **FLOW 6 Procurement** Low stock→PR→PO→WH→Invoice | Scaffold lists | RFQ comparison, GRN, 3-way match |
| **FLOW 7 Lease billing** Lease→Charge→Invoice→Payment→GL | Finance portal + charge engine + journals | Real CoA, reverse/period close UAT with accountant |
| Portal auth / invite | Working | SMTP/outbox for invites on air-gapped LAN |
| Announcements | Working | Scope polish |
| Card request | Working | AxTrax issue remains external |
| Security alerts | Working if poller up | Supervised poller (security phase) |
| Lease dates | Lifecycle command/poller | Auto-terminate after end_date (policy TBD) |
| FM / PM / assets | Models + thin WO | Phase 7 |
| DMS | Catalog | Retention/version policy |
| Management BI | KPI + CRM reports | Phase 13 |
| Production TLS / backup | Docs only | **Deferred** NetAdmin+security UAT |

## Pilot-ready today (functional)

Login, tickets, reception visitors, employee IN/OUT (if AxTrax poller up), card request, announcements, spaces, CRM sales path, lease lifecycle (when poller/`--once` enabled), finance draft→confirm→payment (placeholder CoA).

## Acceptance notes

- Billing is **not** “full accounting” until CoA/VAT signed off.
- AxTrax card “issued” in ERP ≠ written to AxTrax.
- `Space.resident` is bridge; active Lease + `activate_lease` is commercial SoT for occupancy flags.
