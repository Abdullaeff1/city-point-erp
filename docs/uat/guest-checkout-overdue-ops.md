# Qonaq overdue — lokal poller və alıcı siyasəti

**Yenilənib:** 2026-11-27 (Decision 07)

## Üç ayrı hadisə

| Case | Şərt | Alıcı | Event key |
|------|------|-------|-----------|
| A. Cardless portal | `INSIDE`, ID saxlanılmayıb, aktiv qonaq kartı yox, `check_in_at+24h` | Şirkətin aktiv portal üzvləri (`RESIDENT_USER`) | `visitor.checkout_overdue.{visit}.u.{user}` |
| B. ID held, hələ içəridə | `INSIDE` + `id_document_held`, `check_in_at+24h` (sərhəd daxil) | Aktiv **Reception** + **Security** | `visitor.id_held_overdue.{visit}.{rec\|sec}.{user}` |
| C. Çıxış bilinib, vəsiqə qaytarılmayıb | `RETURN_PENDING` | Reception + Security (domain event) | `visitor.return_pending…` — **inside overdue deyil** |

AxTrax OUT = keçid sübutu; vəsiqə/kart fiziki qaytarılmasını təsdiq etmir.

## Poller

| Sahə | Dəyər |
|------|--------|
| Command | `manage.py poll_guest_checkout_overdue` |
| Body | `process_guest_overdue_alerts()` → portal cardless + ID-held inside |
| Start | `bin/dev/entrypoint.py` / `bin/prod/entrypoint.py` |
| Env | `GUEST_CHECKOUT_OVERDUE_POLL_ON_START=1`, `GUEST_CHECKOUT_OVERDUE_POLL_INTERVAL=900` |
| Log | `var/guest_checkout_overdue_poller.log` |

```bash
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py poll_guest_checkout_overdue --once
```

## Bildiriş linkləri

| Case | Reception (`erp`) | Security |
|------|-------------------|----------|
| B ID-held overdue | `/erp/reception/?status=inside_overdue` | `/security/guests/?status=inside_overdue` |
| C return-pending | `/erp/reception/?status=id_pending` | `/security/guests/?status=id_pending` |
| A cardless | Portal `/portal/guests/?overdue=1` | — |

Oxumaq viziti bağlamır; təkrar poll eyni `(user, event_key)` üçün təkrar yaratmır. Preview-də FIN / seriya / kart yoxdur.

## Vaxt sahələri

| Sahə | Məna |
|------|------|
| `check_in_at` | 24 saat sərhədi (yoxdursa `created_at`) |
| `check_out_at` | Jurnal/portalda göstərilən çıxış |
| `actual_departure_at` | Bilinən faktiki çıxış |
| `check_out_recorded_at` | Operator bağladığı vaxt |
| `id_document_returned_at` | Fiziki vəsiqə qaytarılması |
