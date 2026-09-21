# Backup & restore (Phase 1)

A backup is **not** valid until a restore has been tested.

## Scope

- PostgreSQL database `citypoint` (ERP SoT)
- Media files under `MEDIA_ROOT` (document uploads)
- Do **not** backup AxTrax MS SQL as part of ERP backup (separate system)

## Automated backup (recommended)

On the Postgres host or via Compose:

```bash
# Example daily dump
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "backup-$(date +%Y%m%d).sql.gz"
```

Retention suggestion: 14 daily + 8 weekly (adjust with City Point IT).

## Verification

1. Restore dump into a **separate** database name (e.g. `citypoint_restore_test`).
2. Point a throwaway Django settings / compose override at it.
3. `migrate --check` and smoke: login, open ticket list, one AccessEvent count.
4. Record date of last successful restore test in ops log.

## Restore procedure (prod incident)

1. Stop web writers (scale web to 0 / stop gunicorn).
2. Restore dump into target DB (or replace volume from verified backup).
3. Restore media tarball if needed.
4. Start web; verify login + critical flows.
5. Resume AxTrax poller after DB is healthy (cursor is in DB SyncLog).

## Ownership

Document who runs backups and who verifies monthly restore drills (City Point IT / ERP ops).
