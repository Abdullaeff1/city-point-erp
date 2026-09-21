# Phase 0.9 — Business Gap Report

Compared to Final Master Plan e2e flows (§18) and module DoD.

| Flow / capability | Current | Gap |
|-------------------|---------|-----|
| **FLOW 1 New resident** Website→CRM→Lease→Portal→Access→Billing | Partial CRM/Lease models; public API stub; no billing product | Phase 3–4 + 11 |
| **FLOW 2 Employee access** Employee→Credential→AxTrax→Event | Employee + card + read events; no Credential entity; write mock | Phase 5 (+ vendor write later) |
| **FLOW 3 Visitor** Portal→Reception→Access | Pre-reg + reception real; temp AxTrax access mock | Phase 5 |
| **FLOW 4 Technical ticket** Ticket→WO→Warehouse | Ticket+routing real; WO thin; warehouse scaffold | Phase 6–8 |
| **FLOW 5 Commercial request** Ticket→CRM→Offer→Lease | Taxonomy supports commercial; handoff mostly manual/absent in UI | Phase 4 + 6 |
| **FLOW 6 Procurement** Low stock→PR→PO→WH→Invoice | Scaffold lists only | Phase 8–9 + 11–12 |
| **FLOW 7 Lease billing** Lease→Charge→Invoice→Payment→GL | Charge/Invoice models only | Phase 3 foundation + 11–12 |
| Portal auth / invite | Working | Harden portal_active, SMTP |
| Announcements | Working unscoped | Scopes |
| Card request | Creates ticket/order | Status workflow for resident |
| Security alerts | Working if poller runs | Poller reliability |
| FM / PM / assets | Models + thin WO | Phase 7 |
| DMS / kargüzarlıq | Catalog | Phase 10 |
| Management BI | KPI cards | Phase 13 |
| Domain events / approval engine | Stub / unused | Phase 2 |

## Pilot-ready today (with Phase 1 hardening)

Login, tickets, reception visitors, employee IN/OUT (if poller up), card request submit, announcements (after scope fix), spaces list, documents (if files uploaded).
