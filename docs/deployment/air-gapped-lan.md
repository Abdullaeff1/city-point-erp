# Air-gapped / LAN-only deployment (City Point)

**Constraint:** Production ERP runs on a **local server inside City Point**.  
When the system goes live, **there is no public Internet** for the app, browsers on the LAN, or outbound SaaS.

Plan and operate as an **intranet platform**, not a cloud SaaS.

---

## Network model

```text
[ Resident PCs / LAN ]          [ Staff PCs / LAN ]
         │                              │
         └──────────┬───────────────────┘
                    ▼
         City Point LAN switch
                    │
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
  ERP/Portal     AxTrax NG      (optional)
  Docker host    MS SQL RO      internal mail
  PostgreSQL     172.31.x.x     Exchange/SMTP
```

| Link | Required? | Notes |
|------|-----------|--------|
| Browser → ERP/Portal | Yes | LAN HTTP/HTTPS only |
| ERP → PostgreSQL | Yes | Same host / private Docker network |
| ERP host → AxTrax MS SQL | Yes | **LAN only** (already RO) |
| ERP → Internet | **No** | Must not be required at runtime |
| Website (public) → ERP | Optional later | Only if website has a **LAN/VPN path** or separate DMZ; otherwise defer website intake |

---

## Hard runtime rules

1. **No CDN** — fonts, icons, JS must be under `/static/` (Whitenoise).
2. **No pip/docker pull at go-live** — images and wheels pre-loaded on the server (or offline mirror).
3. **Email is not Internet SMTP by default** — use:
   - in-app notifications (always), and/or
   - **internal** Exchange / LAN SMTP, and/or
   - file/`locmem` for invite links printed/copied by admin when no mail server exists.
4. **Website public API** is **not** a Phase-1 launch dependency for air-gapped go-live.
5. **Updates** (Django, OS, Docker) happen via USB / internal package repo on a maintenance window — not `apt`/`pip` from Internet during operation.
6. **Time sync** — NTP to **internal** time server (or domain DC); AxTrax event timestamps depend on correct clocks.

---

## What already fits LAN-only

- Django + Postgres Docker stack
- AxTrax people/events JSON poller (LAN SQL)
- Portal / ERP / Security surfaces
- Invite links as absolute URLs on **LAN hostname** (`http://erp.local` / internal IP)

## What was Internet-dependent (fixed / planned)

| Dependency | Risk without Internet | Action |
|------------|----------------------|--------|
| Google Fonts | Broken typography | System font stack in `cp.css` |
| Lucide via unpkg | Missing icons | Vendor `static/vendor/lucide.min.js` |
| External SMTP | Invites/resets fail | `CP_OFFLINE=1` + internal mail or admin-copy invite URL |
| Public website leads | N/A offline | Defer or LAN-only ingest |
| Docker Hub / PyPI at runtime | Deploy fails | Pre-build images offline |

---

## Production env flags

```env
CP_ENV=production
CP_OFFLINE=1
DJANGO_DEBUG=0
# Internal hostnames only — no public DNS required
DJANGO_ALLOWED_HOSTS=erp.citypoint.local,portal.citypoint.local,10.x.x.x
DJANGO_CSRF_TRUSTED_ORIGINS=http://erp.citypoint.local,http://portal.citypoint.local

# Mail: prefer internal SMTP; if none, use file backend (not console) under CP_OFFLINE=1
EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
EMAIL_FILE_PATH=/app/var/mail_outbox
# Or internal:
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# EMAIL_HOST=mail.citypoint.local
```

With `CP_OFFLINE=1`, production may use **file-based** email (ops read outbox / copy invite URL) instead of forcing Internet SMTP.

---

## Access for residents without Internet

Residents use Portal **on the building LAN** (Wi‑Fi / cable), not via public Internet.

Implications:

- Portal URL is an **internal** name or IP (print on welcome sheet).
- No reliance on resident’s mobile data for core flows.
- Password reset / invite: if no internal mail, admin uses `invite_portal_user` and **hands the link** (or prints QR).

---

## Backup / updates without Internet

- Postgres dumps to local disk / NAS on LAN
- Media volume backups local
- App updates: build image on a connected machine → transfer `.tar` → `docker load` on the air-gapped host

---

## Phase planning impact

| Phase | Offline impact |
|-------|----------------|
| 1 Hardening | CDN removal, offline mail policy, LAN hosts |
| 2–13 | Domain logic unchanged (all on-prem) |
| Website CRM ingest | **Deferred** until LAN/VPN path exists |
| External bank/e-invoice/accounting SaaS | **Interfaces only**; no live cloud until connectivity exists |
| SMS notifications | Out of scope offline |

---

## Go-live checklist (offline)

- [ ] App opens with **network cable unplugged from Internet uplink** (LAN only)
- [ ] Icons and fonts load (no browser console CDN errors)
- [ ] Login, ticket, reception, AxTrax sync work
- [ ] Invite flow works via link copy or internal SMTP
- [ ] Backup/restore tested on local storage
- [ ] AxTrax poller Scheduled Task running on LAN host

**Automated / dev smoke results:** [offline-smoke-checklist.md](./offline-smoke-checklist.md)

**Lokal vs Cloud (tövsiyə + hücumlar):** [local-vs-cloud-security.md](./local-vs-cloud-security.md)
