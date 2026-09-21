# Phase 0.4 — Data Ownership Map

Target owners follow Final Master Plan §2.1. Current owner is what code uses today.

| Entity | Current Owner | Target Owner | Dependencies | Migration Risk |
|--------|---------------|--------------|--------------|----------------|
| Party | parties (partial) | parties | Lease, CRM, Billing, Parking | Med — dual with ResidentCompany |
| Person | parties (partial) | parties | Access, Reception guest link later | High — employees are ResidentEmployee |
| Resident (company) | residents.ResidentCompany | Party + Resident role | Portal users, tickets, spaces | High |
| ResidentEmployee | residents | Person + employment relation | AccessEvent, card order | High |
| Space | property | property | LeaseLine, Asset, meters | Med — retire Space.resident FK |
| Lease | leases | leases | Party, Space | Med |
| Asset | property | FM/property | WO, Space | Low |
| GuestVisit | reception | reception | Guest, company | Low |
| Credential | *(card_number on employee)* | access_control (future) | AxTrax mapping | High when introduced |
| AccessEvent | residents | access domain / integration | Employee, ExternalIdentity | Med move later |
| Ticket | tickets | tickets | Company, routing | Low |
| WorkOrder | maintenance | maintenance | Ticket, Asset | Low–Med |
| Stock | warehouse | warehouse | WO consumption | Low |
| PO / PR | procurement | procurement | Party supplier | Low |
| Charge / Invoice | billing | billing | Party, Lease later | Med |
| Journal | accounting | accounting | Billing events | Med |
| Document | documents | documents/DMS | polymorphic links weak | Med |
| Announcement | comms (global) | comms + scope FKs | Portal | Low–Med |
| ExternalIdentity | integrations | integrations | All sync entities | Low (keep) |

## Ownership rules for Phase 1–2

1. Do not create parallel “Company” tables in CRM/Lease/Accounting.
2. Prefer FK to Party once link exists; keep ResidentCompany until cutover validated.
3. Access write adapters stay in integrations; business eligibility in access/residents services.
