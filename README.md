# city-point-erp

City Point Baku — Resident Portal + Staff ERP (Django 5, PostgreSQL, Docker).

## Quick start (dev)

```bash
cd bin/dev
docker compose up --build
```

Open http://localhost:8000/login/

### Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Portal | `office@asbc.az` | `asbc123` |
| Admin | `admin@citypoint.az` | `admin123` |
| Reception | `reception@citypoint.az` | `reception123` |
| Service Desk | `desk@citypoint.az` | `desk123` |
| Property/FM | `fm@citypoint.az` | `fm123` |
| Management | `manager@citypoint.az` | `manager123` |

## Stack

- Django 5 + PostgreSQL 16
- Docker Compose (`bin/dev`, `bin/prod`)
- i18n: AZ / EN / RU
