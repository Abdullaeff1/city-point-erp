# Environments: development / staging / production

Set `CP_ENV` in the environment file.

| CP_ENV | DJANGO_DEBUG | SEED_DEMO | EMAIL |
|--------|--------------|----------|-------|
| `development` (default) | usually 1 | may be 1 | console OK |
| `staging` | must be 0 | must be 0 | real SMTP required |
| `production` | must be 0 | must be 0 | real SMTP required |

## Boot guards (`config/settings.py`)

- `DEBUG=0` → strong `DJANGO_SECRET_KEY` required
- `CP_ENV=production` → `DEBUG` cannot be 1; `SEED_DEMO` cannot be 1
- `CP_ENV` in staging/production → console email backend rejected

## Environments

See [environments.md](./environments.md) and **[air-gapped-lan.md](./air-gapped-lan.md)** (no-Internet go-live).

## Session / passwords

- Session age default 8 hours (`SESSION_COOKIE_AGE`)
- Password validators: similarity, min length 10, common, numeric

## Email ops

- Invite sends write `NotificationDispatch` (`portal.invite`) with `sent` / `failed`
- Retry: `python manage.py retry_invite_emails`

## AxTrax poller (prod host)

```powershell
# elevated once
powershell -ExecutionPolicy Bypass -File bin/prod/register_axtrax_poller_task.ps1
```

See [axtrax-poller-runbook.md](../integrations/axtrax-poller-runbook.md).
