# Phase 0.3 — Module Status

**Updated:** 2026-11-17 (functional readiness pass).  
Classification: **REAL** = production-usable ops MVP · **THIN** = models + partial UI/services · **SCAFFOLD** = models + list/read UI only.

| Module | Status | Evidence / acceptance |
|--------|--------|------------------------|
| accounts (auth/invite) | REAL | Invite, reset, must_set_password, tests |
| portal | REAL (MVP) | Scope/session; tickets, employees, guests, card order (Ad Soyad Ata adı) |
| reception | REAL | Services + ERP UI + API + tests |
| tickets / service desk | REAL (foundation) | Taxonomy, routing, SLA, portal+ERP UI |
| residents | REAL | Companies, employees, access events, card order |
| security portal | REAL | Alerts, companies, tickets, tests |
| AxTrax read sync | REAL (ops-dependent) | People/events sync + poller; **no vendor write** |
| property / spaces | THIN→REAL ops | Building/Floor/Space UI; occupancy bridged from Lease activate |
| parties | THIN | Models + dual-write bridge; Resident* remains SoT for portal |
| leases | THIN→REAL ops | Activate/terminate cascade; **lifecycle poller** (SIGNED→ACTIVE, ACTIVE→EXPIRING) |
| crm | REAL (sales MVP) | Lead→Opp→Offer versions/approval→LeaseApplication; PDF; Excel import; reports |
| maintenance / WO | THIN | Models + create_wo_from_ticket; list UI |
| documents | THIN | Catalog; versions unused in portal |
| comms | THIN | In-app + NotificationDispatch; CRM offer email via `send_templated_email` when flagged |
| rbac | THIN | Tables exist; not enforced everywhere |
| workflows / approval | THIN | Offer approval wired; generic engine still limited |
| warehouse | SCAFFOLD | Models + apply_movement + list UI |
| procurement | SCAFFOLD | Models + list UI; RFQ placeholder |
| billing | THIN | Charges, invoice confirm, payments; journal errors **surface**; race-safe invoice codes |
| accounting | THIN | CoA placeholder + journals; **not** full GL product |
| api public | THIN | spaces/leads stubs + mock adapters |
| reporting / BI | THIN | ERP KPI + CRM dual reports |
| access_control app | MISSING | Logic in residents + integrations |

**Do not market THIN/SCAFFOLD as production-complete.**  
**Security/TLS/NetAdmin:** deferred — functional UAT first, then harden ([bin/prod](../../bin/prod)).
