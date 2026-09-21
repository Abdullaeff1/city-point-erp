# Phase 0.3 — Module Status

Classification: **REAL** = production-usable ops MVP · **THIN** = models + partial UI/services · **SCAFFOLD** = models + list/read UI only.

| Module | Status | Evidence |
|--------|--------|----------|
| accounts (auth/invite) | REAL | Invite, reset, must_set_password, tests |
| portal | REAL (MVP) | Full routes; gaps: portal_active, announcement scope |
| reception | REAL | Services + ERP UI + API + tests |
| tickets / service desk | REAL (foundation) | Taxonomy, routing, SLA, portal+ERP UI |
| residents | REAL | Companies, employees, access events, card order |
| security portal | REAL | Alerts, companies, tickets, tests |
| AxTrax read sync | REAL (ops-dependent) | People/events sync + poller script; not a Windows service |
| property / spaces | THIN→REAL ops | Building/Floor/Space UI; parking/meters models exist |
| parties | THIN | Models + ERP list + sync_parties command |
| leases | THIN | Activate/terminate services; list/detail UI |
| crm | THIN | Models + convert_offer service; list UI |
| maintenance / WO | THIN | Models + create_wo_from_ticket; list UI |
| documents | THIN | Catalog; versions unused in portal; often no file |
| comms | THIN | In-app notifications; Dispatch outbox unused for SMTP |
| rbac | THIN | Tables exist; not enforced everywhere |
| workflows / approval | SCAFFOLD | ApprovalRequest model only |
| warehouse | SCAFFOLD | Models + apply_movement + list UI |
| procurement | SCAFFOLD | Models + list UI; RFQ placeholder |
| billing | SCAFFOLD | Models + generate_invoice helper + list |
| accounting | SCAFFOLD | CoA + journals models + list |
| api public | THIN | spaces/leads stubs + mock adapters |
| reporting / BI | THIN | KPI cards on ERP reports only |
| access_control app | MISSING | Logic split across residents + integrations |

**Do not market THIN/SCAFFOLD as production-complete.**
