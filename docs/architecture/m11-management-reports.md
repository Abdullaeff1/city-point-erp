# M11 — Rəhbərlik hesabatları

**Status:** icra olunub (2026-11-18)  
**Defer:** rəsmi KPI siyahısı UAT; PDF export; real-time BI warehouse

---

## 1. Hub

| Maddə | Kod |
|-------|-----|
| ERP `/reports/` | `ReportsView` + tab-lar |
| Filter | `date_from` / `date_to` / `company_id` |
| Excel | `reports_export` |
| Domain builders | `apps/erp/exec_reports.py` |

---

## 2. Domenlər

| Hesabat | Mənbə |
|---------|--------|
| Əmlak | doluluq, boş m², bitən lease |
| CRM / Satış | `crm.reports` (hub + ətraflı səhifə) |
| Service Desk | SLA/MTTR (`tickets.reporting`) |
| FM | açıq WO, gecikmiş PM, təkrar repair, aktiv event |
| Anbar/Satınalma | low stock, issue sərf, PR/PO status, supplier |
| Maliyyə | fakturalanmış / ödənmiş / AR / gecikmiş |
| Security | AxTrax health + access/notification say |

---

## 3. Snapshot (backup deyil)

| Maddə | Kod |
|-------|-----|
| Model | `core.ReportSnapshot` |
| Command | `capture_exec_snapshots` |
| UI | tab `history` |

---

## 4. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M11-1 | Management/Admin ACL | test |
| M11-2 | Property/finance builders | test |
| M11-3 | Daily snapshot idempotent | test |
| M11-4 | Excel export | test |

İcazə: yalnız Management + Admin (`RoleRequiredMixin`).
