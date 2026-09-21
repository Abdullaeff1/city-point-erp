# Phase 0.6 — Technical Debt

Prioritized for Phase 1–2 impact.

| ID | Debt | Impact | Target phase |
|----|------|--------|--------------|
| TD-01 | `ResidentCompany` / `ResidentEmployee` dual with `Party` / `Person` | Master-data duplication risk | 2 |
| TD-02 | `Space.resident` FK vs Lease occupancy | Wrong commercial truth | 3 |
| TD-03 | Announcements global, no scope | Cross-tenant info leak risk | 1 |
| TD-04 | `portal_active` not enforced in mixin | Suspended tenants can still log in | 1 |
| TD-05 | AxTrax poller manual; stops silently | Stale access/security data | 1 |
| TD-06 | `SEED_DEMO` default `1` in `bin/dev/entrypoint.py` | Demo passwords in careless prod clones | 1 |
| TD-07 | Console email default | Invites/resets invisible in prod | 1 |
| TD-08 | NotificationDispatch unused for delivery | No reliable ticket/email alerts | 2 / 6 |
| TD-09 | RBAC tables not wired to most views | Role CharField only | 2 |
| TD-10 | Card request lacks status workflow for resident | Opaque “submitted” experience | 5 |
| TD-11 | Public API incomplete / mock website | Commercial intake weak | 4 |
| TD-12 | Scaffold modules in ERP nav | Looks “done” when not | Docs + nav hygiene Phase 1 |
| TD-13 | Document files often missing | Portal “Fayl yoxdur” | 1 / 10 |
| TD-14 | No `access_control` app; events on residents | Harder to grow Credential/Assignment | 5 |
| TD-15 | Guests portal list today-only | Weak history | 5 |
| TD-16 | Limited automated tests outside reception/security/invite/card | Regression risk | Ongoing |
| TD-17 | Password reset not scoped to portal users only | Broad email match | 1 |
| TD-18 | No staging settings split documented as first-class | Env confusion | 1 |

## Explicit non-debt (do not “fix” prematurely)

- Ticket Type/Category/Subcategory + RoutingRule — keep, extend.
- Reception separate from Tickets — correct.
- AxTrax read via adapter/file — correct until vendor write path exists.
