# Legacy ↔ New Architecture Mapping

**Date:** 2026-09-15  
**Status:** Scope 0 baseline  
**Rule:** Existing Portal/ERP MVP must keep working; new models coexist until cutover.

## Current apps

| App | Role today | Target owner |
|-----|------------|--------------|
| `accounts` | User + Role enum + login | `accounts` + `rbac` |
| `residents` | ResidentCompany, Employee, AccessEvent | `parties` (Party/Person) + `access_control` later |
| `property` | Building/Floor/Space/Asset/Contractor | `property` (enhanced) + Party link |
| `reception` | Guest + GuestVisit | Visitor domain (Scope 5) |
| `tickets` | Ticket/SLA/messages/events + services | `tickets` + later FM WO |
| `documents` | Document metadata (+ optional file) | `documents` + versioning |
| `comms` | Announcement, Notification | Notification engine absorbs `Notification` |
| `portal` / `erp` | View shells | Stay thin; services in domain apps |
| *(new)* `core` | — | Base models, helpers |
| *(new)* `parties` | — | Party / Person SoT |
| *(new)* `audit` | — | Cross-cutting audit log |
| *(new)* `rbac` | — | Permission catalog (beyond Role string) |
| *(new)* `workflows` | — | Approval request foundation |
| *(new)* `integrations` | — | Adapter + sync log + external IDs |

## Entity mapping

| Target concept | Legacy source | Migration strategy |
|----------------|---------------|--------------------|
| **Party** (org) | `ResidentCompany` | Create `Party` row; FK `legacy_resident_company` during dual-write; later cutover |
| **Party** (supplier/contractor) | `Contractor` (orphan) | Map to Party role=contractor when used |
| **Person** | `ResidentEmployee`, `Guest`, portal `User` | Person records; link User/Employee/Guest gradually |
| **Lease** | `Space.resident` + `occupancy` + company `contract_*` | **No Lease yet** (Scope 2). Keep Space.resident until Lease Active drives occupancy |
| **Space commercial status** | `Space.occupancy` mixes commercial + ops | Scope 1: split `commercial_status` / `operational_status` |
| **Audit** | `TicketStatusEvent`, `AccessEvent` | Keep domain events; add generic `audit.AuditLog` |
| **Document version** | `Document.version` CharField | Add `DocumentVersion` rows; keep label for UI |
| **Notification** | `comms.Notification` | Foundation outbox wraps same table first |
| **Access credential** | `ResidentEmployee.card_number` | Scope 6 Access Credential |
| **RBAC** | `User.role` TextChoices | Keep role; add `rbac.Permission` grants for fine-grained |

## Space ↔ Resident today (to replace)

```text
Space.resident_id → ResidentCompany
```

**Target:** `Space ↔ Lease ↔ Party`  
Until Scope 2: `Space.resident` remains operational truth for portal/ERP filters.

## Permissions today

| Surface | Gate |
|---------|------|
| Portal | `ResidentPortalMixin` + company FK on User |
| ERP | `StaffRequiredMixin` / `RoleRequiredMixin` |
| Reports | Admin + Management |

Scope 0 adds permission **codes** and role→permission matrix without removing mixins.

## Dual-write policy (Scope 0–2)

1. Writes to `ResidentCompany` also upsert linked `Party` (service).
2. Reads for Portal/ERP stay on legacy FKs.
3. No destructive drop of legacy columns in production migrations.
4. Seed/demo remains source for regression.

## Acceptance for this document

- [x] All current apps inventoried  
- [x] Party/Person/Lease/Audit/Document gaps named  
- [x] Cutover rule: Lease becomes SoT only in Scope 2  
