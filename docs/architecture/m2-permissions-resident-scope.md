# M2 — İcazələr və rezident obyekt scope

**Status:** icra olunub (2026-11-17)  
**Əlaqə:** [m1-party-resident-mapping.md](m1-party-resident-mapping.md) §5, TD-09

---

## 1. Model

| Qat | Mexanizm | Harada |
|-----|----------|--------|
| Kobud rol | `User.role` + mixins | `apps/accounts/mixins.py` |
| Portal şirkət scope | Session + membership | `apps/accounts/portal_scope.py` |
| Obyekt scope (M2) | Company id dəsti; Party = `legacy_resident_company` | `apps/accounts/object_scope.py` |
| İncə RBAC | `PermissionCode` / `RolePermission` | `apps/rbac/services.py` |
| CRM ACL | Ayrı rol dəstləri (Admin ∉ CRM_VIEW) | `apps/crm/access.py` A.10 |

**Qayda:** Rezident üçün Party və company eyni nəticə verir — Party yalnız körpü company id scope-dadır. Cutover yox.

---

## 2. `object_scope` API

- `accessible_company_ids_for(user)` — membership + primary FK  
- `effective_company_ids(user, company_ids=…)` — session ∩ membership  
- `company_accessible` / `party_accessible`  
- `filter_by_company_ids(qs, …)`

---

## 3. Bağlanmış boşluqlar

| Boşluq | Düzəliş |
|--------|---------|
| Ticket attachment/delete yalnız `resident_company_id` | Membership / session scope |
| Portal sənəd: staff scope ids ignore | `company_ids` varsa company ∈ scope |
| Sales / Accountant / Resident RBAC seed yox | `ROLE_MATRIX` genişləndirildi |
| Lease UI bütün ERP staff | `lease.view` / `lease.edit` |
| Management `announcement.publish` bypass | `user_has_permission` A.8 istisna |

---

## 4. ROLE_MATRIX (əlavələr)

| Rol | Əsas kodlar |
|-----|-------------|
| Sales | party.*, lease.view/edit, space.view, approval.view |
| Accountant | party.view, lease.view, document.view, report.view |
| Resident | ticket.view, document.view, party.view (katalog; portal mixin) |
| Property FM | + lease.edit, document.edit |
| Service Desk | + lease.view |
| Security | + ticket.view |

`seed_rbac_catalog()` / `sync_parties` yenidən işlədəndə grant-lər yazılır.

---

## 5. Qəbul meyarları

| # | Meyar | Pass |
|---|--------|------|
| M2-1 | Scope helper mövcud | `object_scope.py` + test |
| M2-2 | Multi-company ticket attachment/delete | membership ilə OK |
| M2-3 | Lease mutate `lease.edit` tələb edir | ERP view + UI |
| M2-4 | Sales/Accountant/Resident matrix seed | `ROLE_MATRIX` |
| M2-5 | A.8 announcement Management grant-only | `user_has_permission` |
| M2-6 | Sənəd | bu fayl + phase-acceptance |

CRM Admin-out (A.10) dəyişmir.
