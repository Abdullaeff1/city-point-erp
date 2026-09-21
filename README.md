# city-point-erp

City Point Baku — Resident Portal + Staff ERP (Django 5, PostgreSQL, Docker).

## Quick start (dev)

```bash
cd bin/dev
docker compose up --build
```

Open http://localhost:3001/login/

### Demo accounts (dev only — never use in production)

`SEED_DEMO=1` seeds these locally. Production must run with `SEED_DEMO=0` and real invites.

| Role | Email | Password |
|------|-------|----------|
| Portal | `office@asbc.az` | `asbc123` |
| Admin | `admin@citypoint.az` | `admin123` |
| Reception | `reception@citypoint.az` | `reception123` |
| Service Desk | `desk@citypoint.az` | `desk123` |
| Property/FM | `fm@citypoint.az` | `fm123` |
| Management | `manager@citypoint.az` | `manager123` |
| Security | `security@citypoint.az` | `security123` |

Open http://localhost:3001/security/ after login as Security.

## Deployment

- Dev: `bin/dev` · Prod (LAN/air-gapped): [`docs/deployment/air-gapped-lan.md`](docs/deployment/air-gapped-lan.md)
- Offline go-live: no CDN; set `CP_OFFLINE=1` (see `bin/prod/.env.example`)

## Master plan status

- **Phase 0–2:** done (audit, hardening code, ERP core foundation)
- **Phase 3–13:** thin-but-real foundations landed — see [`docs/architecture/master-plan-progress.md`](docs/architecture/master-plan-progress.md)
- **To finish production:** business/ops inputs in [`docs/architecture/finish-requirements.md`](docs/architecture/finish-requirements.md)

Scaffold-looking modules now have service workflows; they are **not** full product UX yet.

## Security (prod)

See `docs/security/` — Phase 0 security audit, DB isolation, Portal public / ERP private checklist, Postgres roles, resident invite auth (no public signup).
