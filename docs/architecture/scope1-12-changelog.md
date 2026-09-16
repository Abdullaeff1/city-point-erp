# Implementation changelog — Scope 1–12 foundations

**Date:** 2026-09-15

## Delivered

| Scope | What landed |
|-------|-------------|
| 1 | Space `commercial_status` / `operational_status`, parking, meters |
| 2 | `leases` app, activate/terminate cascade, ERP lease UI |
| 3 | CRM Lead/Opportunity/Offer, offer→lease draft |
| 4 | `GET /api/v1/public/spaces/`, `POST /api/v1/public/leads/` |
| 5 | Portal guest pre-registration + invite_code |
| 6 | Still mock AccessControlAdapter (awaiting vendor schema) |
| 7 | WorkOrder / MaintenancePlan / Inspection + ERP list |
| 8 | Warehouse / SKU / Stock / movements |
| 9 | PR / PO / RFQ stubs |
| 10 | Charge / Invoice engine |
| 11 | Chart of Accounts + Journal models |
| 12 | Reports KPIs: occupancy, vacant m², leads, WO, stock, AR |

## Deferred until real schema

- Turnstile vendor adapter
- Website CMS field alignment beyond contract stub
- External accounting / payment / e-invoice

## Demo

- Lease `LS-1001` (ASBC) active
- Public vacant space `CP-F05-OFF-502`
- Seed lead/offer/WO/warehouse/PR/PO/invoice/CoA
