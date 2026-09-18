# Turnstile / Access Control — Technical Audit Checklist

**Status:** CONNECTIVITY + SCHEMA AUDIT DONE (AxTraxNG / `AxTrax1`)  
**Rule (Master Plan):** **DO NOT GUESS** vendor DB schema. Findings below are from live read-only inspection.

## Connection (verified 2026-09-18)

| Item | Value |
|------|--------|
| Host | `172.31.104.10` |
| Port | `1433` |
| Server instance | `SRV-SQL1\CPDB` |
| Database | **`AxTrax1`** (AxTraxNG) |
| Login | `ReadOnlyerp` (read-only) |
| TCP + SQL auth | OK |

Credentials must live in env / secret store — not in git.

## Vendor

- **Product:** Rosslare **AxTraxNG**
- **Integration mode (phase 1):** DB read / poll (no write — account is read-only)
- **Event stream:** poll `tblEvents` by `IdAutoEvents` / `dtEventReal` (idempotent key: `IdAutoEvents`)

## Core tables → ERP model mapping

### Must use (Phase 1 — employee in/out sync)

| AxTrax table | Role | ERP target |
|--------------|------|------------|
| **`tblDepartment`** | Tenant / şirket qrupları (ASBC, Nestle, A.T.Bank, …) | `ResidentCompany` (match by name/slug) + optional `ExternalIdentity(system=axtrax, type=department)` |
| **`tblEmployees`** | Şəxslər (~1261) | `ResidentEmployee` + `ExternalIdentity(system=axtrax, type=employee, external_id=iEmployeeNum)` |
| **`tblCard`** | Kartlar (~1285); `iCardCode`, `IdEmpNum`, `eCardStatus` | `ResidentEmployee.card_number` (active card where `eCardStatus=1`) |
| **`tblEvents`** | Hadisə tarixçəsi (~2.8M); əsas tip **`iEventType=17`** ≈ Access Granted | `AccessEvent` |
| **`tblReader`** | Oxuyucu; **`bReaderOut`**: `0/False` → **IN**, `1/True` → **OUT** | `AccessEvent.event_type` (`in` / `out`) |

**AccessEvent sync formula (proposed):**

```text
tblEvents (iEventType = 17, IdEmpNum > 0)
  + tblReader.bReaderOut  →  in | out
  + dtEventReal           →  occurred_at
  + IdEmpNum              →  ResidentEmployee via ExternalIdentity
  + IdAutoEvents          →  sync cursor / idempotency
```

Readers named `*TurIN` / `*Ent*IN` / `*TurOUT` / `*Ent*OUT` confirm the `bReaderOut` convention.

### Useful later (Phase 2 — context / UI)

| AxTrax table | Use |
|--------------|-----|
| `tblDoor` | Door label on event detail |
| `tblAccessGroup` | Access rights display (not payroll) |
| `tblAccessArea` / `tblAreaReaders` | Zone/area labels |
| `tblPanel` / `tblNetworks` / `tblSite` | Device topology |
| `tblCredentialType` | Card vs other credential types |

### Visitor / Reception (Phase 3 — needs write API or elevated DB rights)

| AxTrax | ERP |
|--------|-----|
| `tblEmployees` visitor fields (`iVisitorUser`, `bVisitDate`, `dtVisitDateTime`, …) | `VisitorAccess` / `GuestVisit` |
| Today: **0** employees flagged as visitor in this DB | Grant/revoke **cannot** be done with read-only login |

Phase 1 should **not** invent visitor card push into AxTrax. Keep `MockAccessControlAdapter` for Reception until write path exists (vendor API or dedicated service account).

### Explicitly out of scope for ERP access sync

| Tables | Why |
|--------|-----|
| `tblMessages` (~1M), camera/Hikvision/Dahua/ViTrax | Video/alarms — not Portal attendance |
| `tblBio*`, fingerprint/face | Biometrics — separate consent/compliance |
| `tblTA*` (Time Attendance) | AxTrax TA module ≠ our `AccessEvent`; do not auto-post to payroll/accounting |
| `tblHLX*`, operators, reports, downloads | AxTrax internal ops |

## Observed data notes

- Departments map cleanly to City Point tenants (e.g. **ASBC** = 45 users).
- Active cards: `eCardStatus=1` (~1278); status `2` rare.
- `iEventType=17` dominates (~2.68M) — treat as **granted access** for sync.
- Some event rows have corrupt future timestamps (`2125-…`); filter `dtEventReal < '2100-01-01'` and prefer `IdAutoEvents` cursor.
- Employee display names sometimes embed card meta in `tFirstName`/`tFullName` — prefer structured fields + `tblCard.iCardCode`.

## ERP adapter interface (unchanged)

```text
AccessControlAdapter
  upsert_person(person) -> ExternalIdentity      # phase 2/3 write
  assign_credential(person, credential) -> result  # phase 3 write
  revoke_credential(credential) -> result          # phase 3 write
  fetch_events(since) -> list[NormalizedAccessEvent]  # phase 1 READ
  health_check() -> ok|error
```

Phase 1 implementation: **`AxTraxNgReadAdapter.fetch_events`** + management command → `AccessEvent`.

## Checklist

- [x] Vendor name and product version family (AxTraxNG / DB `AxTrax1`)
- [x] Integration mode: DB link (read-only poll)
- [x] Auth: SQL login `ReadOnlyerp`
- [x] Person / card / department schemas inspected
- [x] Event stream: poll `tblEvents`; idempotent id `IdAutoEvents`
- [ ] Grant/revoke card semantics — **blocked** (read-only; needs vendor/IT write path)
- [x] Staging/production host reachable from office network
- [ ] Data residency / retention policy confirmation from City Point IT
- [ ] Department ↔ `ResidentCompany` matching rules approved (name match vs manual map table)

## Recommended next implementation steps

1. Env: `TURNSTILE_MSSQL_*` / `TURNSTILE_MSSQL_PASSWORD` (never commit secrets).
2. People: `python manage.py sync_axtrax_people --file=var/axtrax_people.json`
3. Events poll (default **15 saniyə**):
   ```powershell
   $env:TURNSTILE_MSSQL_PASSWORD = '***'
   powershell -File bin/dev/poll_axtrax_events.ps1 -IntervalSec 15
   ```
   One-shot: add `-Once`. Import only: `python manage.py sync_axtrax_events --file=var/axtrax_events.json`
4. Portal `/portal/employees/access/` shows synced `AccessEvent` rows.
5. Defer visitor credential push until write access or AxTrax API is available.

**Latency:** poll 15s → rezidentlər adətən **&lt;30 saniyə** gecikmə ilə görür.
