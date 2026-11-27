# Functional readiness UAT checklist

Security/TLS/NetAdmin **out of scope** for developer code Pass; operator §E is tracked with NetAdmin. Mark each row Pass / Fail / Blocked.

**CRM production gate:** §A bütün sətirlər Pass + [crm-written-acceptance.md](crm-written-acceptance.md) imzası olmadan CRM production-a çıxarılmır və “hazır” hesab edilmir.

**Mərhələ meyarları + sübut:** [phase-acceptance-criteria.md](phase-acceptance-criteria.md) (A–E).  
**Boşluqlar / P0–P3:** [../architecture/phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md)

| Bölmə | Kod hazır? | Operator Pass? | Tracker |
|-------|------------|----------------|---------|
| §A CRM→Lease | Bəli | **Xeyr** | [crm-written-acceptance.md](crm-written-acceptance.md) |
| §B Lease lifecycle | Bəli | **Xeyr** | bu fayl |
| §C Daily ops | Bəli | **Xeyr** (Ops imza) · engineering Pass 2026-11-27 | [section-c-engineering-pass-2026-11-27.md](section-c-engineering-pass-2026-11-27.md) + [../ops/axtrax-ro-dod-status-2026-11-27.md](../ops/axtrax-ro-dod-status-2026-11-27.md) |
| §D Billing | Bəli (placeholder CoA) | **Xeyr** | [coa-import-uat.md](coa-import-uat.md) |
| §E Security/ops | Sənəd | **Xeyr** | [../deployment/netadmin-handoff-checklist.md](../deployment/netadmin-handoff-checklist.md) |

## A. CRM → Lease

**Yazılı qəbul statusu:** `AWAITING_SIGNATURE` — [crm-written-acceptance.md](crm-written-acceptance.md)

- [ ] Lead create → Opportunity → Offer version
- [ ] Management approval required before send
- [ ] Offer PDF generates; send marks SENT (email only if `CRM_OFFER_SEND_EMAIL=1`)
- [ ] LeaseApplication → draft Lease with bank requisites / form fields
- [ ] CRM sales vs director reports load without error
- [ ] Excel import (`import_crm_leads_xlsx`) on sample file

## B. Lease lifecycle / Space

- [ ] Signed lease with `start_date` ≤ today activates via `poll_lease_lifecycle --once`
- [ ] Activate sets Space commercial active + `Space.resident` from party bridge
- [ ] Active lease with `end_date` within notice window → EXPIRING + in-app notify
- [ ] Terminate clears portal/billing flags and vacates space occupancy

## C. Daily ops

Engineering sübut: [section-c-engineering-pass-2026-11-27.md](section-c-engineering-pass-2026-11-27.md). Ops checkbox = operator imza.

- [x] Portal card order: label/placeholder **Ad Soyad Ata adı**; creates employee + security ticket *(eng 2026-11-27)*
- [x] Reception check-in / check-out *(eng 2026-11-27 — unit 54 OK + UI)*
- [ ] Security company employees + access day view matches AxTrax events (read-only) — **Blocked:** RO LAN; [../ops/axtrax-ro-dod-status-2026-11-27.md](../ops/axtrax-ro-dod-status-2026-11-27.md)
- [x] Ticket create → assign → (optional) WO from ticket *(eng 2026-11-27 — TK-1040→WO-1106)*

## D. Billing (not full GL)

**CoA UAT:** [coa-import-uat.md](coa-import-uat.md) — `AWAITING_CLIENT_COA`

- [ ] Monthly lease charges generate
- [ ] Invoice from charges → confirm creates journal (failure must error, not silent success)
- [ ] Payment records journal; paid status when covered
- [ ] Accountant: trial balance opens; CoA is placeholder — do not sign as statutory books until CoA UAT Pass

## E. Deferred (security / NetAdmin)

**Handoff:** [../deployment/netadmin-handoff-checklist.md](../deployment/netadmin-handoff-checklist.md) (NA1–NA9)

- [ ] TLS / reverse proxy / secure cookies
- [ ] `private_media` + outbox volumes + backup restore drill
- [ ] `cp_migrator` vs `cp_app` deploy split
- [ ] Supervised AxTrax/lease pollers + healthchecks
