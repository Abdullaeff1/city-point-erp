# Turnstile / Access Control — Technical Audit Checklist

**Status:** BLOCKED pending real vendor materials  
**Rule (Master Plan):** **DO NOT GUESS** vendor DB schema or API. Only adapter interface + mock until audit completes.

## Required inputs (from vendor / IT)

- [ ] Vendor name and product version
- [ ] Integration mode: REST API / SDK / DB link / file drop
- [ ] Auth method and secret storage requirements
- [ ] Person / card / access group / device entity schemas
- [ ] Event stream format (push webhook vs poll) + idempotent event id
- [ ] Grant/revoke card semantics and latency SLA
- [ ] Staging environment credentials
- [ ] Data residency / GDPR constraints

## ERP adapter interface (safe to implement now)

```text
AccessControlAdapter
  upsert_person(person) -> ExternalIdentity
  assign_credential(person, credential) -> result
  revoke_credential(credential) -> result
  fetch_events(since) -> list[NormalizedAccessEvent]
  health_check() -> ok|error
```

Mock adapter used in tests. Real vendor adapter only after checklist signed.

## Current legacy touchpoints

- `ResidentEmployee.card_number`
- `AccessEvent` (in/out) — demo/seed, not live turnstile sync

## Explicit non-goals until audit

- No vendor-specific SQL against turnstile DB
- No invented column names
- Access events never auto-post to payroll/accounting
