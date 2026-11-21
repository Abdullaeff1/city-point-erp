# Phase 6 — On-site UAT (Workflows A–E)

Local development verification is complete in Docker. Live rows below are signed only when the named City Point owner records an observed result on site. AxTrax write remains out of scope.

## Common evidence

Retain: screen screenshot or PDF, record code (visit/ticket/WO/PR/PO/lease), actor username, date/time (Baku).

---

## A — Reception → Security (guest)

| # | Owner | Start | Action | Expected | Live ✓ |
|---|-------|-------|--------|----------|--------|
| A1 | Reception | Pre-registered or walk-in guest | Check-in with ID held | Visit INSIDE; audit `visit.check_in` | |
| A2 | NetAdmin/Security | Guest card + OUT reader (QONAQ identity confirmed) | Physical exit through OUT reader | Electronic exit; if ID held → RETURN_PENDING; `access_event_id` on audit; notify Reception + Security (display name only, no FIN/card) | |
| A3 | Reception | RETURN_PENDING visit | Complete ID return | Visit LEFT; Reception notify; custody cleared | |
| A4 | Resident (portal) | Guest still INSIDE | Portal checkout | LEFT; no Security RETURN_PENDING path | |

**RETURN_PENDING (single entry):** Electronic exit with ID still held → status `RETURN_PENDING`. **Who must act:** Reception completes physical ID return (`complete_id_return`). **Who is notified today:** every active `Role.SECURITY` + `Role.RECEPTION` (complete delivery, `order_by("pk")`, no `[:20]` cap; display name only). **Pending CP decision (owner: City Point Security+Reception):** keep all-role visibility, or restrict delivery to a named duty team (and specify the assignment source). Change recipients only with written policy.

---

## B — Resident → Helpdesk → Facility

| # | Owner | Start | Action | Expected | Live ✓ |
|---|-------|-------|--------|----------|--------|
| B1 | Resident Co A | Portal | Submit WO-eligible incident | Ticket routed; Helpdesk sees it | |
| B2 | Helpdesk | Open ticket | Create WO | FM notified; WO on facility list | |
| B3 | FM | Open WO | Assign + complete | Helpdesk notified of technical completion; ticket not auto-closed | |
| B4 | Helpdesk | Ticket after WO complete | Resolve with resident-safe note | Resident sees resolution; no enrichment notes / WO code | |
| B5 | Resident Co B | Co A ticket URL | Open | 404 / no access | |

---

## C — Sales → Property → Lease → Finance

| # | Owner | Start | Action | Expected | Live ✓ |
|---|-------|-------|--------|----------|--------|
| C1 | Sales | Approved offer | Lease application → submit to accounting | Accountant in-app notify; app on list | |
| C2 | Accountant | Submitted app | Accept / lease draft / sign path | Lease created; activation on start_date via lifecycle job | |
| C3 | Sales/Admin | ACTIVE lease near end | Run / wait lifecycle | One expiry warning; retry does not duplicate | |

**Open (Finance):** CoA/VAT and deposit-due policy remain Finance UAT (`coa-import-uat.md`).

---

## D — Facility → Warehouse → Procurement

| # | Owner | Start | Action | Expected | Live ✓ |
|---|-------|-------|--------|----------|--------|
| D1 | FM/WH | Low stock or WO shortage | PR → approve → RFQ/PO → partial receive ×2 | Two receipt audits; replay same key no second success | |
| D2 | WH | Stock after receive | Issue to WO + confirm | `warehouse.issue.confirm` audit; assignee notify | |

---

## E — Department → Management

| # | Owner | Start | Action | Expected | Live ✓ |
|---|-------|-------|--------|----------|--------|
| E1 | FM | Document requiring approval | Submit → Management approve | FM notify references version; FM opens Documents (not decide hub) | |
| E2 | FM | Over-limit priced quote | Select quote → Management commitment | process_only ≠ spending; commitment amount in history | |
| E3 | Management | Pending hub | Decide document / commitment | Originator notified; second decide blocked | |

**Open:** Admin override → Management alert policy; tax_basis; non-AZN.

---

## AxTrax read-only

| Check | Expected | Live ✓ |
|-------|----------|--------|
| Poller / sync | Reads events/people; no credential write from ERP | |
| Replay OUT event | No duplicate guest notify | |
| Link loss | SyncLog / health visible; no invented exits | |
