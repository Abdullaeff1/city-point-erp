# Functional readiness UAT checklist

Security/TLS/NetAdmin **out of scope** for this pass. Mark each row Pass / Fail / Blocked.

## A. CRM → Lease

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

- [ ] Portal card order: label/placeholder **Ad Soyad Ata adı**; creates employee + security ticket
- [ ] Reception check-in / check-out
- [ ] Security company employees + access day view matches AxTrax events (read-only)
- [ ] Ticket create → assign → (optional) WO from ticket

## D. Billing (not full GL)

- [ ] Monthly lease charges generate
- [ ] Invoice from charges → confirm creates journal (failure must error, not silent success)
- [ ] Payment records journal; paid status when covered
- [ ] Accountant: trial balance opens; CoA is placeholder — do not sign as statutory books

## E. Deferred (security later)

- [ ] TLS / reverse proxy / secure cookies
- [ ] `private_media` + outbox volumes + backup restore drill
- [ ] `cp_migrator` vs `cp_app` deploy split
- [ ] Supervised AxTrax/lease pollers + healthchecks
