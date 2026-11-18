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

**Defer:** end_date-dən sonra avtomatik terminate; Party/`Space.resident` cutover; formal renewal workflow (RENEWED status + yeni Lease sətiri).

---

## 6. Space sahə modeli (yoxlanıb)

| Sahə | Model | Qeyd |
|------|--------|------|
| Kod | `Space.code` unique | Building→Floor→Space |
| Ölçü | `area_m2`, `rentable_area_m2` | LeaseLine.area_m2 override |
| Kommersiya | `commercial_status` | vacant/reserved/contracted/active/notice |
| Texniki | `operational_status` | available/maintenance/blocked |
| Mərtəbə | `Space.floor` → Floor → Building | ERP space/lease UI |

## 7. Kommersiya status keçidləri (Lease → Space)

| Lease status | Space.commercial_status |
|--------------|-------------------------|
| draft | vacant |
| negotiation | reserved |
| approved / signed | contracted |
| active / renewed / amended | active |
| expiring | notice |
| terminated | vacant (başqa open lease yoxdursa) |

Mənbə: `apps/leases/services.py` `sync_space_from_lease`.

## 8. Depozit / parent tarixçə

- `DepositSettlement` — lease detail-də siyahı + `settle_deposit` POST
- `Lease.parent_lease` — uzadılma/amendment zənciri (UI link); avtomatik renewal wizard **defer**

## 9. Parkinq / sayğac / tarif qaydaları

| Element | Harada | Qayda |
|---------|--------|--------|
| Parkinq | `ParkingAssignment.lease` (+ party/space fallback) | Lease detail siyahısı; `parking_included_free` / `parking_notes` |
| Sayğac | `UtilityMeter.space` ∈ lease spaces | Lease detail — sahə sayğacları |
| Kirayə tarif | `rent_rate_per_m2` | Charge = m² × tarif (prorrata) |
| Xidmət | `service_rate_per_m2` | eyni |
| Depozit | `deposit_months` × aylıq kirayə və ya `deposit` | `compute_lease_amounts` |
| Əlavə | `LeaseAddon.rate_per_m2` | Aktiv əlavələr charge-ə düşür |
| Güzəşt | (ayrı model yox) | Endirim məbləği notes/addon ilə; formal discount cədvəli **defer** |

Parkinq charge yaradılmır (`generate_monthly_lease_charges` — A.4).
