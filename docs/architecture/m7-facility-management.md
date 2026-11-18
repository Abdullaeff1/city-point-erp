# M7 — Facility Management

**Status:** icra olunub (2026-11-18)  
**Defer:** anbar material e2e (M8), Party cutover

---

## 1. Aktiv / inventar

| Sahə | Kod |
|------|-----|
| Kateqoriya, kod, yer | `BuildingAsset` |
| İstehsalçı, seriya, zəmanət, sənəd | eyni + migration `0011` |
| Tarixçə | `BuildingAssetEvent` (install/repair/inspection/decommission) |

---

## 2. Work Order

Ticket / space / asset / building_asset / contractor / assignee / cost lines / billable↔internal.

---

## 3. Preventive Maintenance

| Maddə | Kod |
|-------|-----|
| Frequency daily…yearly | `PlanFrequency` / `MaintenancePlan` |
| Due → WO | `generate_work_orders_for_due_plans` + `poll_maintenance_plans` |
| Inspection nəticə / təsdiq | `confirm_inspection` |

---

## 4. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M7-1 | Asset metadata | model + ERP form |
| M7-2 | PM → WO | test |
| M7-3 | Inspection confirm + repair event | test |
| M7-4 | Billable vs internal | mövcud cost sheet |

UAT operator Pass ayrıca.
