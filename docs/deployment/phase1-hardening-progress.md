# Phase 1 — Production hardening progress

Updated: 2026-09-21

## Done in code / docs

| Item | Status |
|------|--------|
| `portal_active` gate | Done |
| Announcement scopes | Done |
| Password reset eligibility | Done |
| Secret / CP_ENV / SEED_DEMO / SMTP console guards | Done |
| Strong password validators + 8h session | Done |
| Invite email delivery log + `retry_invite_emails` | Done |
| AxTrax health dashboard + CLI | Done |
| Windows Scheduled Task registrar | `bin/prod/register_axtrax_poller_task.ps1` |
| Environments doc | [environments.md](./environments.md) |
| Staging `.env.example` | `bin/staging/.env.example` |
| Backup/restore doc | [phase1-backup-restore.md](../backup/phase1-backup-restore.md) |
| Pilot checklist | [phase1-pilot-checklist.md](./phase1-pilot-checklist.md) |
| Prod entrypoint no seed | Already |

## Ops remaining (outside repo)

- [ ] Fill real SMTP credentials on staging/prod
- [ ] Run `register_axtrax_poller_task.ps1` on sync host (elevated)
- [ ] Schedule DB backup + complete one restore drill
- [ ] Execute pilot checklist with 1–2 real companies

When ops items are checked, Phase 1 DoD is met → start Phase 2 (ERP Core).
