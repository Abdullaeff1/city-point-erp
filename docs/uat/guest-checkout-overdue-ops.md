# Qonaq checkout overdue — lokal poller və alıcı siyasəti

**Tarix:** 2026-11-23

## Poller

| Sahə | Dəyər |
|------|--------|
| Command | `manage.py poll_guest_checkout_overdue` |
| Start | `bin/dev/entrypoint.py` / `bin/prod/entrypoint.py` → `start_guest_checkout_overdue_poller()` |
| Env | `GUEST_CHECKOUT_OVERDUE_POLL_ON_START=1` (default), `GUEST_CHECKOUT_OVERDUE_POLL_INTERVAL=900` (saniyə) |
| Log | `var/guest_checkout_overdue_poller.log` |
| Restart | Web konteyner hər start-da poller-i yenidən qaldırır (AxTrax / lease pattern) |

Bir dəfəlik yoxlama:

```bash
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py poll_guest_checkout_overdue --once
```

## Alıcı siyasəti (cari)

**Aktiv `PortalCompanyMembership` + `RESIDENT_USER`** — ziyarətin şirkətinə üzv olan portal istifadəçiləri (qonaq siyahısını görə bilən eyni auditoriya).

Kataloqda ayrıca `guest.manage` PermissionCode yoxdur. Auditoriyanı daraltmaq **City Point təsdiqini** gözləyir; təsdiq olmadan dəyişdirilmir.

## Vaxt sahələri (backend)

| Sahə | Məna |
|------|------|
| `check_out_at` | Jurnal/portalda göstərilən çıxış vaxtı |
| `actual_departure_at` | Bilinən faktiki çıxış (opsional) |
| `check_out_recorded_at` | Operatorun bağladığı vaxt |

UI sadədir: çıxış varsa vaxt, yoxdursa **—**.
