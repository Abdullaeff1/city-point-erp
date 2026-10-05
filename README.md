# city-point-erp

City Point Baku — Resident Portal + Staff ERP (Django 5, PostgreSQL, Docker).

## Quick start (dev)

```bash
cd bin/dev
cp .env.example .env   # set TURNSTILE_MSSQL_PASSWORD for AxTrax on City Point LAN
docker compose --env-file .env up --build
```

Open http://localhost:3001/login/

**Teammate on same LAN (AxTrax like a working PC):** [`docs/deployment/teammate-axtrax-lan.md`](docs/deployment/teammate-axtrax-lan.md)

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
- **AlmaLinux 10 NetAdmin tam rəhbər (Docker yox, bütün şəbəkə variantları):** [`docs/deployment/CityPoint_AlmaLinux10_NetAdmin_Tam_Rehberi.docx`](docs/deployment/CityPoint_AlmaLinux10_NetAdmin_Tam_Rehberi.docx)
- AlmaLinux 10 native offline (eyni məzmunun köhnə adı): [`docs/deployment/CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx`](docs/deployment/CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx)
- AlmaLinux 10 Docker variant (alternativ): [`docs/deployment/CityPoint_AlmaLinux10_Deploy_Rehberi.docx`](docs/deployment/CityPoint_AlmaLinux10_Deploy_Rehberi.docx)
- Offline go-live: no CDN; set `CP_OFFLINE=1` (see `bin/prod/.env.example`)

## Master plan status

- **Phase 0–2:** done (audit, hardening code, ERP core foundation)
- **Phase 3–13:** thin-but-real foundations landed — see [`docs/architecture/master-plan-progress.md`](docs/architecture/master-plan-progress.md)
- **To finish production:** business/ops inputs in [`docs/architecture/finish-requirements.md`](docs/architecture/finish-requirements.md)

Scaffold-looking modules now have service workflows; they are **not** full product UX yet.

## Security (prod)

See `docs/security/` — Phase 0 security audit, DB isolation, Portal public / ERP private checklist, Postgres roles, resident invite auth (no public signup).
