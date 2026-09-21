# Phase 0.2 — Entity / Database Map

Primary models by app (choices/enums omitted). Full FK detail is in migrations.

## Core / identity

| Model | App | Notes |
|-------|-----|-------|
| User | accounts | email unique; role; `resident_company` FK; `must_set_password` |
| PortalInvite | accounts | hashed token, TTL, one-time |
| Party | parties | UUID; optional `legacy_resident_company` OneToOne |
| PartyRole | parties | role codes on Party |
| Person | parties | FK Party; kind |
| PermissionCode / RolePermission | rbac | foundation |
| AuditLog | audit | central log |
| ApprovalRequest | workflows | stub approval |

## Property

| Model | Key relations |
|-------|---------------|
| Building → Floor → Space | Space.`resident` → ResidentCompany (legacy occupancy) |
| Asset | → Space |
| Contractor | standalone |
| ParkingZone → ParkingSpot → ParkingAssignment | Assignment → Party optional |
| UtilityMeter → MeterReading | → Space |

## Residents / access (current home of access events)

| Model | Key relations |
|-------|---------------|
| ResidentCompany | `portal_active`, `is_internal`, status |
| ResidentEmployee | → Company; card; access_level; soft deactivate |
| AccessEvent | → Employee; IN/OUT; reader fields; AxTrax ids |
| RapidCardSwipeAlert / ShaftAccessAlert | → Employee / Event |

## Reception

Guest → GuestVisit → VisitorAccess; VisitorType; statuses for visit and access sync.

## Tickets

TicketType/Category/Subcategory → RoutingRule → Department/Queue + SlaPolicy  
Ticket → messages, attachments, TicketStatusEvent, TicketRoutingEvent  
Related employee for card orders.

## Commercial / ops foundations

| App | Models |
|-----|--------|
| leases | Lease (→ Party), LeaseLine (→ Space) |
| crm | Lead, Opportunity, Offer (→ Party) |
| maintenance | WorkOrder, MaintenancePlan, Inspection |
| warehouse | Warehouse, Bin, SKU, Stock, StockMovement |
| procurement | PurchaseRequest/Line, PurchaseOrder/Line, RFQ |
| billing | Charge, Invoice, InvoiceLine (→ Party) |
| accounting | Account, JournalEntry, JournalLine |
| documents | DocumentType, Document, DocumentVersion |
| comms | Announcement (unscoped), Notification, NotificationDispatch |
| integrations | ExternalIdentity, SyncLog |

## Important legacy / dual paths

1. **ResidentCompany** is SoT for portal/ops today; **Party** has optional link via `legacy_resident_company`.
2. **Space.resident** FK shortcuts occupancy; LeaseLine also points at Space — dual model.
3. **Person** exists but portal employees are **ResidentEmployee**, not Person.
4. No Credential / AccessAssignment tables yet — card number on ResidentEmployee; events on AccessEvent.

## Indexes (highlights)

- ResidentEmployee: `(company, is_active, full_name)`
- AccessEvent: time + employee oriented indexes (see residents migrations)
- ExternalIdentity: system + external_id uniqueness pattern

## Status fields (selected)

CompanyStatus, LeaseStatus, TicketStatus, VisitStatus, WorkOrderStatus, InvoiceStatus, PR/PO statuses, SyncStatus.
