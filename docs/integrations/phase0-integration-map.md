# Phase 0.5 — Integration Map

## AxTrax NG (access control)

```text
AxTrax1 (MS SQL, ReadOnlyerp)
  → PowerShell export (people / events JSON under var/)
  → Django manage.py sync_axtrax_people | sync_axtrax_events
  → ResidentCompany / ResidentEmployee / AccessEvent
  → ExternalIdentity + SyncLog (cursor)
  → rapid_swipe / shaft_access detectors
```

| Aspect | Status |
|--------|--------|
| People sync | Implemented (`axtrax_people_sync.py`) |
| Events sync | Implemented (`axtrax_events_sync.py`), cursor via SyncLog |
| Access level map | Implemented (group/readers → level 1/2) |
| Poller | `bin/dev/poll_axtrax_events.ps1` — **manual process**, not service |
| Write (grant/revoke) | **Mock only** — `MockAccessControlAdapter` |
| ERP DB | PostgreSQL only — AxTrax is never the ERP database |

Docs: [turnstile-audit.md](./turnstile-audit.md).

## Website

| Direction | Status |
|-----------|--------|
| Public spaces API | `/api/v1/public/spaces/` stub |
| Public leads API | `/api/v1/public/leads/` + mock adapter |
| Contract | [website-contract.md](./website-contract.md) — incomplete vs real site |

## Email / communications

| Channel | Status |
|---------|--------|
| Invite / password reset | Django `send_mail` |
| Default backend | **Console** unless `EMAIL_*` set |
| NotificationDispatch | Outbox model exists; not a full delivery worker |
| SMS | Future |

## Reception API

Staff JSON endpoints under `/api/reception/…` for visits and today board (`apps.api.views_reception`).

## Adapter principle (preserve)

All vendor-specific calls behind `apps.integrations.adapters` Protocols. Do not invent AxTrax write schemas.
