# city-point-erp

City Point Baku — Resident Portal + Staff ERP (Django 5, PostgreSQL, Docker).

## Quick start (dev)

```bash
cd bin/dev
docker compose up --build
```

Open http://localhost:3001/login/

### Demo accounts

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

## Stack

- Django 5 + PostgreSQL 16
- Docker Compose (`bin/dev`, `bin/prod`) — host port **3001**
- i18n: AZ / EN / RU

## Scope status (Master Plan)

- **Scope 0:** Party/Person, Audit, RBAC, workflows, integrations adapters, document versions
- **Scope 1:** Space commercial/operational status, parking, meters
- **Scope 2:** Lease lifecycle + activate/terminate cascade
- **Scope 3:** CRM Lead / Opportunity / Offer → Lease draft
- **Scope 4:** Public API stubs `/api/v1/public/spaces|leads` (mock-safe)
- **Scope 5:** Portal guest pre-registration + invite code
- **Scope 6:** Turnstile — AxTraxNG read sync (see `docs/integrations/turnstile-audit.md`)
- **Scope 7–11:** FM Work Orders, Warehouse, Procurement, Billing, Accounting foundations
- **Scope 12:** Expanded management KPIs on Reports

## Security (prod)

See `docs/security/` — DB isolation decision, Portal public / ERP private checklist, Postgres roles, resident invite auth (no public signup).
