# AxTrax events poller — reliability runbook (Phase 1)

When the web container starts and `TURNSTILE_MSSQL_PASSWORD` is set, Django starts `poll_axtrax` in the background (`AXTRAX_POLL_ON_START=1`). Log: `var/axtrax_poller.log`.

The Windows host script remains an alternative if the container cannot reach AxTrax SQL.

## Dev / ops start

```powershell
cd <repo>
# TURNSTILE_MSSQL_PASSWORD must be set in the session
powershell -File bin/dev/poll_axtrax_events.ps1
```

- Interval default: 15s
- Export: `var/axtrax_events.json`
- Import: `docker compose exec web python manage.py sync_axtrax_events --file=var/axtrax_events.json`

People (less frequent):

```powershell
powershell -File bin/dev/export_axtrax_people.ps1
# then sync_axtrax_people
```

## Production expectation

1. Run poller as a **Windows Scheduled Task** or service that restarts on failure (do not rely on an interactive terminal).
2. Monitor health:
   - ERP dashboard (Admin / Management): AxTrax sync card
   - CLI: `python manage.py axtrax_sync_status`
3. If AxTrax is down: Reception, tickets, and portal continue; access data becomes stale until sync resumes.
4. Never reset the events cursor without an explicit ops decision.

## Manual catch-up

1. Confirm password env and network to `172.31.104.10`.
2. Start poller; first cycles may export TOP 5000 batches until caught up.
3. Verify `axtrax_sync_status` shows recent `last_event_sync_at`.

## Failure records

Successful and cursor updates land in `integrations.SyncLog`. Investigate ERROR rows there; retry by re-running the poller (duplicate protection via `ExternalIdentity` event keys).
