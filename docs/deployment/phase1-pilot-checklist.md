# Phase 1 — Controlled pilot checklist

DoD: 1–2 real resident companies use portal without critical defects.

## Before invite

- [ ] `CP_ENV=staging` or `production`, `SEED_DEMO=0`, SMTP real
- [ ] Company exists; `portal_active=True`
- [ ] AxTrax poller scheduled; `axtrax_sync_status` OK
- [ ] Backup restore drill logged ([phase1-backup-restore.md](../backup/phase1-backup-restore.md))

## Pilot users

```bash
docker compose exec web python manage.py invite_portal_user \
  --email=... --company=<slug> --first-name=... --last-name=... \
  --base-url=https://portal.citypoint.az --send-email
```

Check Admin → NotificationDispatch `portal.invite` = sent.

## Smoke (each company)

- [ ] Login + set password via invite
- [ ] Home / spaces / announcements (only building + own company)
- [ ] Create ticket + reply thread
- [ ] Guest pre-registration → reception sees visit
- [ ] Employees access / card request submit
- [ ] Password reset email arrives

## Pass criteria

No P0 bugs on smoke; AxTrax events appear within poller interval; no cross-company announcement leak.
