# Party / Space / Lease — Data Model (Approval Checkpoint)

**Status:** APPROVED for implementation (user direction 2026-09-15). Website/turnstile real schemas deferred.  
**Scope:** Model design for Scopes 0–2. Scope 0+ implements Party/Person; Scope 1–2 Space/Lease live.

## 1. Party (Single Source of Truth for identity)

```text
Party
  id, uuid
  party_type: organization | person
  legal_name
  brand_name (optional)
  tax_id (VÖEN) optional
  status: prospect | active | inactive | blocked
  roles: M2M / flags — resident, prospect, supplier, contractor, partner, other
  emails / phones / addresses (contact points)
  legacy_resident_company_id (nullable, unique)  # dual-write bridge
  created_at, updated_at
```

**Rules**

- CRM, Lease, Procurement, Accounting reference **Party**, never duplicate company tables.
- `ResidentCompany` remains until Portal cutover; then becomes a view/facade or is retired.

## 2. Person

```text
Person
  id, uuid
  full_name
  email, phone (optional)
  party (FK, nullable) — employer / associated org
  person_kind: resident_employee | contact | visitor | contractor_employee | staff
  user (OneToOne User, nullable) — portal/staff login link
  legacy_employee_id / notes for migration
  is_active
```

## 3. Space (enhanced — Scope 1)

Keep Building → Floor → Space → Asset.

Add (Scope 1, not destructive yet):

```text
Space
  ...existing fields...
  commercial_status: vacant | reserved | contracted | active | notice | vacant
  operational_status: available | maintenance | blocked
  rentable_area_m2 (may alias area_m2 initially)
  # current_lease FK added when Lease exists
```

**Rule:** Do not use `Space.resident_id` as long-term SoT. Bridge until Lease Active.

## 4. Lease (Scope 2 — not implemented in Scope 0)

```text
Lease
  code
  party (tenant)
  space (or lease lines for multi-space)
  status: draft → negotiation → approved → signed → active → expiring → renewed|amended|terminated
  start_date, end_date
  rent, currency, deposit, service_charge
  parent_lease (for amendment/renewal chain)
```

**Activation cascade (service):**  
Lease Active → Space commercial=active → Party resident active → Portal eligible → Access eligible → Billing on.

## 5. ER (conceptual)

```text
Party 1──* Person
Party 1──* Lease
Space 1──* Lease (history)
Lease *──* DocumentVersion
```

## 6. Sign-off checklist

- [ ] Party fields approved (tax_id required or not?)
- [ ] Multi-space lease: single Lease with lines vs multiple Lease rows?
- [ ] Amendment = new Lease row linked to parent (recommended)
- [ ] Keep `ResidentCompany.slug` as Party external code?

**Until signed:** implement Party/Person + bridge only; do not remove `Space.resident`.
