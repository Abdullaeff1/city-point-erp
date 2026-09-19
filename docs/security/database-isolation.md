# Database isolation — City Point ERP (NetAdmin qərar qeydi)

**Status:** Accepted architecture (2026-09)  
**Product DB:** PostgreSQL `citypoint` (Django `default`)  
**Vendor DB (separate):** AxTraxNG `AxTrax1` on MS SQL — read-only sync only

## Decision

Do **not** split City Point ERP into per-department physical databases (procurement / FM / warehouse / web). Domains share ForeignKeys and one business process. Isolation is achieved with **network, roles, and application RBAC**, not multi-DB.

## Why not multi-DB

- Tickets, reception, spaces, billing, work orders, and warehouse reference the same companies/spaces/parties.
- Django cannot enforce cross-database ForeignKeys or atomic joins.
- Splitting would require a rewrite (opaque IDs + sync) and adds inconsistency risk without stopping an app-level compromise.

## Correct isolation model

| Layer | Control |
|-------|---------|
| Network | PostgreSQL never on the public internet; only app servers |
| DB roles | `cp_app` (DML), `cp_migrator` (DDL deploy), `cp_readonly` (SELECT), `cp_backup` |
| App | Staff ERP vs Resident Portal; company-scoped portal queries; RBAC |
| Vendor | AxTrax remains a separate MS SQL instance; ERP login is SELECT-only on approved tables |

## AxTrax tables (SELECT only)

**Required:** `tblDepartment`, `tblEmployees`, `tblCard`, `tblEvents`, `tblReader`  
**Do not grant:** `tblMessages`, `tblBio*`, `tblTA*`, cameras, HLX/ops tables  
**Optional later:** `tblDoor`, `tblAccessGroup`, `tblAccessArea`, `tblAreaReaders`, panels/networks/site, `tblCredentialType`

## Related docs

- [resident-portal-access.md](resident-portal-access.md) — public Portal vs private ERP
- [postgres-roles.md](postgres-roles.md) — role SQL / runbook
- [network-checklist.md](network-checklist.md) — firewall and host exposure
