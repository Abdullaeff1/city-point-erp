# NetAdmin handoff — 9 tapşırıq

**Məqsəd:** Developer Todoist M1–M12 bağlandıqdan sonra qalan **NetAdmin** işləri.  
**Qayda:** Bu siyahı developer-i gözlətməməlidir; icra City Point IT / NetAdmin.  
**İstinad:** [../architecture/m12-acceptance-integration.md](../architecture/m12-acceptance-integration.md) §4 · [../security/network-checklist.md](../security/network-checklist.md) · [air-gapped-lan.md](air-gapped-lan.md) · [../backup/phase1-backup-restore.md](../backup/phase1-backup-restore.md)

**Cari status:** `9 OPEN` (2026-11-18)

---

## Tracker

| # | Tapşırıq | Owner | Due | Done |
|---|----------|-------|-----|------|
| NA1 | Server OS / yerləşdirmə (native vs Docker) | NetAdmin | | ☐ |
| NA2 | DNS + HTTPS sertifikat (LAN adları və ya IP) | NetAdmin | | ☐ |
| NA3 | LAN/VPN — rezident Portal vs staff ERP giriş modeli | NetAdmin | | ☐ |
| NA4 | Firewall / port (Postgres, AxTrax, app yalnız LAN) | NetAdmin | | ☐ |
| NA5 | Postgres `cp_app` / `cp_migrator` / backup rolları | NetAdmin | | ☐ |
| NA6 | AxTrax RO host + poller maşını (Task/systemd) 24/7 | NetAdmin | | ☐ |
| NA7 | Daxili NTP sahibi / domain time sync | NetAdmin | | ☐ |
| NA8 | Backup NAS + **restore drill** (tarix qeyd) | NetAdmin | | ☐ |
| NA9 | Offline update (`docker load` / RPM mirror) | NetAdmin | | ☐ |

---

## NA1 — OS / yerləşdirmə

| Sahə | Cavab |
|------|-------|
| Host OS | ☐ Windows Server · ☐ Linux: ____ · ☐ digər |
| App runtime | ☐ Docker Compose · ☐ native Python/systemd |
| Host adı / IP | |

Bax: [environments.md](environments.md) · `bin/prod/.env.example`

---

## NA2 — DNS + TLS

| Sahə | Cavab |
|------|-------|
| Portal adı | məs. `portal.citypoint.local` |
| ERP adı | məs. `erp.citypoint.local` |
| Sertifikat | ☐ daxili CA · ☐ self-signed · ☐ yox (HTTP LAN) · ☐ digər |
| Reverse proxy | ☐ nginx · ☐ IIS · ☐ digər · ☐ yox |

UAT §E: TLS / reverse proxy / secure cookies.

---

## NA3 — LAN / VPN giriş

| Kim | Şəbəkə / VLAN | URL |
|-----|---------------|-----|
| Rezident (Portal) | | |
| Staff (ERP) | | |
| VPN tələb? | ☐ Bəli · ☐ Xeyr (yalnız LAN) | |

---

## NA4 — Firewall

Checklist əsası: [../security/network-checklist.md](../security/network-checklist.md)

- [ ] World → Postgres `5432` deny
- [ ] App → Postgres allow (private)
- [ ] AxTrax MS SQL yalnız sync host-dan
- [ ] İctimai `/erp/` / `/admin/` yox (air-gap)

---

## NA5 — Postgres rolları

Runbook: [../security/postgres-roles.md](../security/postgres-roles.md)

- [ ] `cp_migrator` yalnız deploy/migrate
- [ ] `cp_app` DML, DDL yox
- [ ] `cp_backup` / dump credentials ≠ `cp_app`
- [ ] Prod `POSTGRES_USER` = `cp_app`

---

## NA6 — AxTrax RO + poller

| Sahə | Cavab |
|------|-------|
| Sync host | |
| Supervizor | ☐ Scheduled Task · ☐ systemd |
| Health | `axtrax_sync_health` / status OK |

Credentials: [../ops/p0-go-live-answers.md](../ops/p0-go-live-answers.md) P0.6 · Runbook: [../integrations/axtrax-poller-runbook.md](../integrations/axtrax-poller-runbook.md)  
**Write API yox** — yalnız RO.

---

## NA7 — NTP

| Sahə | Cavab |
|------|-------|
| NTP / DC sahibi | |
| ERP + AxTrax host eyni vaxt zonası? | ☐ Bəli |

---

## NA8 — Backup + restore drill

Prosedur: [../backup/phase1-backup-restore.md](../backup/phase1-backup-restore.md)

| Sahə | Cavab |
|------|-------|
| Backup hədəf (NAS path) | |
| Cədvəl (daily/weekly) | |
| Son **uğurlu restore drill** tarixi | __________ |
| Kim icra etdi | |

UAT §E: `private_media` + outbox volumes + restore.

---

## NA9 — Offline update

Bax: [air-gapped-lan.md](air-gapped-lan.md)

| Proses | Qeyd |
|--------|------|
| Image transfer | ☐ `docker load` · ☐ digər |
| OS/patch mirror | ☐ RPM/APT mirror · ☐ USB · ☐ digər |
| Son sınaq tarixi | |

---

## Bağlandıqdan sonra

1. [../uat/functional-readiness-checklist.md](../uat/functional-readiness-checklist.md) §E Pass.
2. [../architecture/phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md) NetAdmin / P2 yeniləyin.
3. Todoist NetAdmin 9 tapşırığı bağlayın (ops tərəfi).
