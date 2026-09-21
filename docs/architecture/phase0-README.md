# Phase 0 — Repository Audit Index

**Date:** 2026-09-21  
**Scope:** Final Master Implementation Plan §4 / §32  
**Rule:** No major rewrite in Phase 0. Working Reception, Tickets, Security, AxTrax read are preserved.

## Audit artifacts

| # | Artifact | Path |
|---|----------|------|
| 1 | Current Architecture Map | [phase0-architecture-map.md](./phase0-architecture-map.md) |
| 2 | Entity / Database Map | [../data-model/phase0-entity-map.md](../data-model/phase0-entity-map.md) |
| 3 | Module Status | [phase0-module-status.md](./phase0-module-status.md) |
| 4 | Data Ownership Map | [../data-model/phase0-data-ownership.md](../data-model/phase0-data-ownership.md) |
| 5 | Integration Map | [../integrations/phase0-integration-map.md](../integrations/phase0-integration-map.md) |
| 6 | Technical Debt | [phase0-technical-debt.md](./phase0-technical-debt.md) |
| 7 | Security Audit | [../security/phase0-security-audit.md](../security/phase0-security-audit.md) |
| 8 | Migration Risks | [../migration/phase0-migration-risks.md](../migration/phase0-migration-risks.md) |
| 9 | Business Gaps | [phase0-business-gaps.md](./phase0-business-gaps.md) |
| 10 | Recommended Order | [phase0-recommended-order.md](./phase0-recommended-order.md) |

## Decision summary (after audit)

### Preserve (do not rewrite)

- Reception visitor lifecycle + services
- Ticket taxonomy / routing / SLA foundation / status events
- Security portal + rapid-swipe / shaft alerts
- AxTrax **read** people + events sync (JSON poll path)
- Portal invite / must_set_password / password reset
- Resident portal ticket + guest pre-reg + employee access + card-order foundation

### Extend (Phase 1+)

- `portal_active` enforcement, announcement scopes, SMTP, poller reliability
- Ticket routing admin UX, SLA business calendar, notifications
- Card-request status workflow
- Lease / CRM / Space occupancy via Lease history
- Party/Person incremental linking

### Migrate (incremental, later)

- `ResidentCompany` / `ResidentEmployee` → `Party` / `Person` (FK link → dual-write → cutover)
- `Space.resident` FK → occupancy via active Lease
- Document metadata → real files + DMS registry

### Deprecate (after cutover)

- Demo seed credentials in production path (`SEED_DEMO` default on)
- Treating scaffold list UIs as production modules
- Unscoped global announcements as the only feed

### Genuinely missing

- Access Control domain models (Credential, AccessAssignment, …) — events live on residents today
- Central Approval engine usage beyond `workflows.ApprovalRequest` stub
- Domain events bus
- Billing charge engine / Accounting journals as products
- Reliable AxTrax poller as a service (manual PowerShell today)
- Staging environment separation docs/config

## Next step

**Phase 1 — Production Hardening** (see [phase0-recommended-order.md](./phase0-recommended-order.md)).
