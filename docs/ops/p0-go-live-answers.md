# P0 go-live cavabları (ops / biznes)

**Məqsəd:** Pilotu bloklayan sualları **müştəri/ops cavabı** ilə bağlamaq.  
**Qayda:** Developer placeholder cavab yazmır. Boş sahələr = gate açıq.  
**İstinad:** [../architecture/finish-requirements.md](../architecture/finish-requirements.md) §B/C · [../architecture/phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md) §3

**Cari status:** `AWAITING_ANSWERS` (2026-11-18)

---

## P0.1 — CRM yazılı qəbul

| Sahə | Cavab |
|------|-------|
| UAT §A Pass? | ☐ Bəli · ☐ Xeyr · Tarix: ______ |
| Satış imza | [../uat/crm-written-acceptance.md](../uat/crm-written-acceptance.md) — status: `AWAITING_SIGNATURE` |
| Qəbul edən | |

---

## P0.2 — Daxili mail

| Variant | Seçim |
|---------|-------|
| LAN SMTP / Exchange | ☐ Host: ________ Port: ____ TLS: ☐ |
| Yalnız offline invite | ☐ `CP_OFFLINE=1` + admin invite link kopyalama |

Qərar verən: _______________ · Tarix: __________

**Kod davranışı (hazır):** `CP_OFFLINE=1` → SMTP fail raise etmir; URL outbox-da qalır.

---

## P0.3 — Portal / ERP LAN hostname / IP (+ TLS)

| Servis | Hostname və ya IP | HTTPS / TLS? |
|--------|-------------------|--------------|
| Portal (rezident) | | ☐ Bəli · ☐ Xeyr (HTTP LAN) |
| ERP (staff) | | ☐ Bəli · ☐ Xeyr |
| `DJANGO_ALLOWED_HOSTS` / CSRF origins | (yuxarıdakılar + localhost) | |

Qərar: _______________ · Tarix: __________

---

## P0.4 — İlk 1–2 pilot şirkət

| # | Hüquqi ad | Portal kontakt (email) | `space_code` / məkan | Qeyd |
|---|-----------|------------------------|----------------------|------|
| 1 | | | | |
| 2 | | | | |

Pilot mühit: ☐ staging · ☐ production · Tarix: __________

---

## P0.5 — Demo wipe

| Sual | Cavab |
|------|-------|
| Pilot/prod bazasında `seed_demo` datası silinsinmi? | ☐ Bəli wipe · ☐ Xeyr (təmiz DB artıq) · ☐ N/A |
| `SEED_DEMO` | Prod/staging: **0** (kod guard artıq) |
| Wipe icra edən / tarix | |

---

## P0.6 — AxTrax RO + poller host

**Engineering status (2026-11-27):** poller prosesi işləyir; `172.31.104.10` bu hostdan **unreachable** — [axtrax-ro-dod-status-2026-11-27.md](axtrax-ro-dod-status-2026-11-27.md). NetAdmin aşağıdakı cədvəli doldurur.

| Sahə | Cavab |
|------|-------|
| AxTrax MS SQL host | `172.31.104.10` (dev default; təsdiq: ____) |
| Port | `1433` |
| DB adı (`AxTrax1`?) | |
| RO user | (parol secret store — git-ə yazma) |
| Poller maşını (hostname) | |
| Supervizor | ☐ Windows Task · ☐ systemd · ☐ digər: ____ · ☑ Docker `AXTRAX_POLL_ON_START` (dev) |
| Interval | 15s (dev default) |

Runbook: [../integrations/axtrax-poller-runbook.md](../integrations/axtrax-poller-runbook.md) · LAN: [../deployment/teammate-axtrax-lan.md](../deployment/teammate-axtrax-lan.md)

---

## Bağlandıqdan sonra

1. [../deployment/phase1-pilot-checklist.md](../deployment/phase1-pilot-checklist.md) «Before invite» doldurun.
2. Staging `.env`: `SEED_DEMO=0`, `DJANGO_ALLOWED_HOSTS`, mail/`CP_OFFLINE`, AxTrax RO.
3. [../architecture/phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md) P0 sətirlərini yeniləyin.
