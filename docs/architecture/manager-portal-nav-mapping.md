# Rəhbərlik portalı — EstatePro → City Point xəritə

**Status:** tətbiq olunur (2026-11-24)  
**Tema:** `.cp-theme-mgmt` (tünd sidebar, açıq content — EstatePro quruluşu, CP navy/qızıl)  
**Kod:** `apps/accounts/mgmt_nav.py`, `apps/erp/management_hub.py`, `static/css/cp-mgmt.css`

## Canlı menyu qrupları

| Qrup | Nümunə marşrutlar | İcazə |
|------|-------------------|--------|
| İdarə paneli | `/erp/` | landing |
| Əmlak və icarə | `/erp/spaces/`, `?status=vacant\|occupied`, `/erp/leases/?filter=expiring`, rezidentlər | `space.view`, `lease.view`, `resident.view` |
| Kommersiya | CRM lid/imkan/təklif/müraciət/hesabat | `crm.view` (edit yox) |
| Bina əməliyyatları | helpdesk, ticket, WO, planlar, içəridə | `ticket.view`, `work_order.view` |
| Anbar və satınalma | warehouse, procurement, suppliers | `warehouse.view` / `procurement.view` |
| Sənədlər və kommunikasiya | documents, correspondence, alerts, elanlar | `document.view` |
| Maliyyə və təsdiqlər | `/erp/approvals/`, `payment-approvals/?queue=ar\|ap`, aging | `approval.view` / `decide` |
| Hesabatlar | `/erp/reports/`, CRM export | `report.view` / `crm.export` |

## EstatePro — dəstəklənməyən (menyuda yox)

Calendar, Settings, Property Types/Amenities, Sales listings/commissions, Inspections, Messages/SMS templates, Owner statements. Qəbul masası şöbə portalıdır (`/erp/reception/` → redirect).

## AR / AP

- AR: `?queue=ar` — kiracı ödəniş təsdiqi (qeyd yarada bilər)
- AP: `?queue=ap` — təchizatçı ödəniş **icazəsi**; settlement/post yalnız Mühasib

## Screenshot-lar

- `docs/uat/screenshots/mgmt-before-desktop.png`
- `docs/uat/screenshots/mgmt-after-desktop.png`
- `docs/uat/screenshots/mgmt-after-payment-ap.png`
- `docs/uat/screenshots/mgmt-after-mobile.png`
- `docs/uat/screenshots/mgmt-after-mobile-account.png`
