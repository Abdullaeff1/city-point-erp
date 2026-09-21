# Phase 0.7 — Security Audit

## Findings

| Severity | Finding | Location / note | Remediation phase |
|----------|---------|-----------------|-------------------|
| High | Demo credentials documented in README; seed creates them | `README.md`, `seed_demo` | 1 — prod forbid SEED_DEMO |
| High | `SEED_DEMO` defaults to on in dev entrypoint | `bin/dev/entrypoint.py` | 1 — prod entrypoint must default off |
| High | `portal_active` not checked | `ResidentPortalMixin` | 1 |
| Medium | Announcements unscoped (all companies see all) | `comms.Announcement`, portal views | 1 |
| Medium | Default `DJANGO_SECRET_KEY` unsafe if env missing | `config/settings.py` | 1 — fail closed in prod |
| Medium | Email console backend default | settings | 1 — require SMTP in prod |
| Medium | Password reset matches any active user by email | accounts forms | 1 — tighten policy |
| Medium | AxTrax password only via env (good) but poller not monitored | poll scripts | 1 — health + service |
| Low | FIN / PII on reception — need field-level perms long-term | reception models | 2 / 5 |
| Low | Public API unauthenticated stubs | `/api/v1/public/*` | 4 — rate limit + spam |
| Info | CSRF middleware on; secure cookies when `DEBUG=0` | settings | Keep |
| Info | Security role blocked from ERP | `can_access_erp` | Keep |
| Info | Docs exist for isolation / network / postgres roles | `docs/security/*` | Follow in deploy |

## Positive controls already present

- Invite-only portal (no public signup) — [resident-portal-access.md](./resident-portal-access.md)
- Role separation portal / erp / security
- CSRF, session auth, Whitenoise
- Prod compose / `.env.example` stubs without real secrets
- AxTrax read-only SQL login (external)

## Production checklist (Phase 1 exit)

- [ ] `DEBUG=0`, strong `DJANGO_SECRET_KEY`
- [ ] `SEED_DEMO=0`, no demo users
- [ ] SMTP configured; invite test delivered
- [ ] HTTPS + secure cookies + CSRF trusted origins
- [ ] Portal host ≠ ERP host (network checklist)
- [ ] Postgres roles least privilege
- [ ] Backup + restore tested
- [ ] AxTrax poller health visible to admin
