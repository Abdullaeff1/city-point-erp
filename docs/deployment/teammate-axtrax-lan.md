# Teammate: eyni LAN-da AxTrax (dev Docker)

Siz və həmkarınız **eyni `main`** kodu ilə işləyirsiniz. AxTrax məlumatı **git-də gəlmir** — həmkarın notebooku **sizin qoşulduğunuz City Point LAN-a** (eyni port/VLAN) qoşulmalı və `bin/dev/.env`-də AxTrax şifrəsi olmalıdır.

## Şərtlər

1. Notebook **sizin istifadə etdiyiniz LAN portu / eyni şəbəkəyə** qoşulu olsun (internet Wi‑Fi kifayət etməyə bilər).
2. Docker Desktop işləsin.
3. Repo: `main` + `git pull`.
4. `bin/dev/.env` — `TURNSTILE_MSSQL_PASSWORD` **sizin `.env`-dəki ilə eyni** (şifrəni gitə yazmayın; birbaşa göndərin).

## Addımlar (həmkarın notebookunda)

```powershell
git checkout main
git pull origin main

cd "bin\dev"
copy .env.example .env
# .env açın → TURNSTILE_MSSQL_PASSWORD=... (həmkardan alın)

docker compose --env-file .env up --build
```

Brauzer: http://localhost:3001/login/  
Demo: `admin@citypoint.az` / `admin123`

## AxTrax yoxlama

LAN-dan SQL-ə çatıb-çatmadığını yoxlayın (PowerShell):

```powershell
Test-NetConnection 172.31.104.10 -Port 1433
```

`TcpTestSucceeded : True` olmalıdır. `False` → NetAdmin: notebook IP-sinə AxTrax RO `:1433` icazəsi.

Poller status:

```powershell
docker compose --env-file .env exec web python manage.py axtrax_sync_status
docker compose --env-file .env exec web tail -40 var/axtrax_poller.log
```

## Keçmiş hadisələr (sizdəki kimi dolu olsun)

Yeni Docker DB boşdur. İlk dəfə backfill:

```powershell
docker compose --env-file .env exec web python manage.py backfill_axtrax_events --from=2026-09-01
```

People/kart siyahısı lazımdırsa (runbook):

```powershell
docker compose --env-file .env exec web python manage.py sync_axtrax_people
```

## Nə eyni olur / nə olmur

| Eyni | Fərqli |
|------|--------|
| Kod (`main`) | Hər kəsin **öz** Postgres volume-u |
| AxTrax mənbəyi (LAN SQL) | Demo seed + öz sync tarixi |
| Login URL localhost:3001 | Sizin PC-dəki bütün ticket/qonaq tarixi avtomatik köçmür |

Tam eyni ERP məlumatı (ticket və s.) lazımdırsa — ayrıca DB dump/restore razılaşdırın. **Yalnız Access/AxTrax** üçün LAN + `.env` + poller + backfill kifayətdir.

## Sizin (işləyən PC) göndərməli olduğunuz

1. `TURNSTILE_MSSQL_PASSWORD` (etibarlı kanal)
2. Bu faylın linki: `docs/deployment/teammate-axtrax-lan.md`
3. Lazım olsa NetAdmin-ə: digər notebookun IP-si üçün `172.31.104.10:1433` allow
