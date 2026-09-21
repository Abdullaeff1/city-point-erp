# Information needed to finish production (City Point)

**Deployment assumption:** go-live is **LAN / air-gapped** (local server, no public Internet).  
See [../deployment/air-gapped-lan.md](../deployment/air-gapped-lan.md).

Provide these so remaining DoD items can be closed without guessing.

## A. Business / process

1. **SLA targets** (response + resolution hours) per Ticket Type / Category / priority + business calendar (work hours, holidays).
2. **Final ticket taxonomy** confirmation vs live City Point cases (which subcategories are WO-eligible / CRM-eligible).
3. **Card request** owners and status rules (who moves Submitted→Issued; when card_number is written).
4. **Lease commercial rules**: rent/SC calculation, indexation, deposit, parking inclusion, fit-out periods.
5. **Billing calendar**: invoice day, due days, VAT/tax treatment, penalty rules.
6. **Chart of Accounts** real codes (replace minimal 1000/1100/4000 seed) + who posts journals.
7. **Approval matrix**: who approves lease / PR / offers / sensitive documents.
8. **Announcement policy**: default building-wide vs company-only; who can publish.

## B. Integrations (LAN-first)

1. **Internal mail?** LAN Exchange/SMTP host — or confirm **invite-by-link** (admin copies URL; `CP_OFFLINE=1` file outbox).
2. **LAN hostnames / IPs** for Portal and ERP (printed for residents; no public DNS required).
3. **AxTrax** RO connectivity from ERP host (already LAN); write docs only if vendor supports later.
4. **Website** public Internet intake is **deferred** unless you provide a LAN/VPN path to ERP.
5. Confirm AxTrax poller host + Windows Scheduled Task.

## C. Environments / ops (offline)

1. Offline Docker image transfer process (build elsewhere → `docker load` on site).
2. Postgres roles; **local/NAS backup** schedule + restore drill (no cloud backup assumed).
3. Internal NTP / domain time sync owner.
4. First **1–2 pilot resident companies** (legal names, portal contacts, spaces).
5. Whether demo seed must be wiped before pilot.

## D. Content / data

1. Real document PDFs for portal (leases, house rules) — stored on server disk.
2. Space photos / descriptions (for future website; optional for LAN go-live).
3. Historical data to migrate (if any Excel/legacy systems).

Until A+B+C are provided, engineering can continue polishing UX/tests, but **cannot** honestly mark Phases 3–13 as business-complete.
