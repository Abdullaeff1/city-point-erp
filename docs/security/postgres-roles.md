# PostgreSQL roles runbook (`citypoint`)

Use **separate roles** on the same database. Do not give the runtime app a superuser or DDL-capable login.

## Roles

| Role | Used by | Privileges |
|------|---------|------------|
| `cp_migrator` | Deploy / `migrate` only | CONNECT, DDL on app schemas, DML as needed for migrations |
| `cp_app` | Django web (prod `POSTGRES_USER`) | CONNECT + DML (SELECT/INSERT/UPDATE/DELETE) on app tables; **no** DROP/TRUNCATE/CREATE |
| `cp_readonly` | BI / ad-hoc reports | CONNECT + SELECT only |
| `cp_backup` | `pg_dump` | CONNECT + SELECT (or use `pg_dump` as migrator offline) |

## Bootstrap (example)

Run as PostgreSQL superuser after the database exists. Adjust passwords via secret store — never commit real secrets.

```sql
-- Roles
CREATE ROLE cp_migrator LOGIN PASSWORD 'CHANGE_ME_MIGRATOR';
CREATE ROLE cp_app LOGIN PASSWORD 'CHANGE_ME_APP';
CREATE ROLE cp_readonly LOGIN PASSWORD 'CHANGE_ME_READONLY';

GRANT CONNECT ON DATABASE citypoint TO cp_migrator, cp_app, cp_readonly;

\c citypoint

GRANT USAGE ON SCHEMA public TO cp_migrator, cp_app, cp_readonly;
GRANT ALL ON SCHEMA public TO cp_migrator;

-- After first migrate (as migrator), grant DML on existing tables to app:
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cp_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public
  GRANT SELECT ON TABLES TO cp_readonly;
```

## Deploy procedure

1. Set env for migration job: `POSTGRES_USER=cp_migrator` → `python manage.py migrate`
2. Set runtime env: `POSTGRES_USER=cp_app` (web container)
3. Never run the web process as `cp_migrator`

## Dev note

Local `bin/dev` may keep a single `citypoint` superuser-style role for speed. Production must use the split above (`bin/prod/.env`).

See also: [database-isolation.md](database-isolation.md), [network-checklist.md](network-checklist.md).
