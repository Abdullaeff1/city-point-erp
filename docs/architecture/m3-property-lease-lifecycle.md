# M3 — Əmlak, sahələr və Lease lifecycle

**Status:** icra olunub (2026-11-17)  
**Əlaqə:** [party-space-lease-model.md](party-space-lease-model.md) §7, TD-02 (cutover yox)

---

## 1. Occupancy SoT

| Sual | Qayda |
|------|--------|
| Kommersiya sakini | Aktiv/expiring **Lease** (`Lease.party`) |
| `Space.resident` | Bridge — activate yazır, terminate təmizləyir (başqa open lease yoxdursa) |
| Multi-space | Primary `Lease.space` + bütün `LeaseLine.space` |

Cutover / `Space.resident` silinməsi **M3-də yox** (TD-02).

---

## 2. Lifecycle cascade

| Hadisə | Nəticə |
|--------|--------|
| Activate | Status ACTIVE; billing/portal/access on; bütün sahələr commercial=active + occupancy + resident; company `portal_active`; Party ACTIVE + RESIDENT; `ensure_primary_lease_line` |
| Expiring | ACTIVE→EXPIRING; commercial=notice (bütün sətirlər); in-app + `LEASE_EXPIRING` (`event_key`) |
| Terminate | Flags off; commercial vacant (başqa open lease yoxdursa); resident clear; company portal off **yalnız** digər open lease yoxdursa |

Poller: `manage.py poll_lease_lifecycle`.

---

## 3. Draft → LeaseLine

`LeaseService.create_draft` və CRM `create_lease_draft` primary space üçün avtomatik `LeaseLine` yaradır (`ensure_primary_lease_line`).

---

## 4. ERP

- Lease detail: sahə sətirləri cədvəli  
- Spaces mərtəbə KPI: `occupancy` / `commercial_status` (yalnız `resident_id` deyil)

---

## 5. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M3-1 | Activate multi-space | Primary + lines bridge |
| M3-2 | Terminate bridge clear | `resident=None`, vacant |
| M3-3 | Portal cascade | Son open lease bitəndə portal off |
| M3-4 | Draft LeaseLine | create_draft / CRM |
| M3-5 | Expiring | Mövcud + lines notice |
| M3-6 | Test | `test_lifecycle.py` |

**Defer:** end_date-dən sonra avtomatik terminate; Party/`Space.resident` cutover.
