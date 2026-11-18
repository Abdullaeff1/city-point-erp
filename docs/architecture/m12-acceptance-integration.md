# M12 — Qəbul sınaqları və inteqrasiya

**Status:** icra olunub (2026-11-18) — lokal/mock qəbul  
**Defer (NetAdmin):** TLS, host, firewall, DB rolları, backup drill, portal DNS — section NetAdmin  
**Defer:** AxTrax **write** (vendor təsdiqi; ayrıca layihə)

---

## 1. Test sübutu

| Sahə | Harada |
|------|--------|
| 7 flow smoke | `apps/core/tests/test_m12_acceptance.py` |
| Email / fayl fail | eyni + M9 outbox |
| AxTrax təkrar hadisə | `sync_event_rows` skipped_existing |
| Demo ≠ prod | `seed_demo` → `CP_ENV=production` CommandError; settings SEED_DEMO guard |
| CRM import audit | `import_crm_leads_xlsx --apply` → `crm.leads.import_xlsx` |
| M5–M11 modul testləri | `apps/*/tests/test_m*.py` |

---

## 2. Biznes axınları (lokal qəbul)

| # | Axın | Mock/Pass |
|---|------|-----------|
| 1 | Lease → charge → invoice → payment → JE | test |
| 2 | Ticket → WO | test |
| 3 | Portal guest pre-register | test |
| 4 | Low stock → PR dedupe | test |
| 5 | CRM lead→offer | mövcud CRM testləri |
| 6 | Employee access read | AxTrax RO + dedupe test |
| 7 | Offline invite / outbox | M9 |

Staging UAT checklist: `docs/uat/functional-readiness-checklist.md` + `phase-acceptance-criteria.md`.

---

## 3. Demo / fixture

| Qayda | Kod |
|-------|-----|
| Dev | `SEED_DEMO=1` + `seed_demo` / `docs/data/*.json` |
| Staging | `SEED_DEMO=0` (istisna: açıq `=1`) |
| Production | `SEED_DEMO=0` məcburi; `seed_demo` qadağan |

---

## 4. NetAdmin handoff (developer hazır; icra ops)

**Tam 9 maddə tracker:** [../deployment/netadmin-handoff-checklist.md](../deployment/netadmin-handoff-checklist.md) (NA1–NA9).  
Bax həmçinin: `docs/deployment/air-gapped-lan.md`, `docs/security/network-checklist.md`, `bin/prod/.env.example`.

| # | Maddə | Status |
|---|--------|--------|
| N1 / NA2 | TLS / host / DNS | NetAdmin — açıq |
| N2 / NA4 | Firewall LAN-only | NetAdmin — açıq |
| N3 / NA5 | Postgres rolları (`cp_app` / migrator) | NetAdmin — açıq |
| N4 / NA8 | Backup + restore drill | NetAdmin — açıq |
| N5 / NA6 | AxTrax RO poller systemd/task | NetAdmin — açıq |
| N6 | `CP_OFFLINE=1` / SMTP | Ops — [../ops/p0-go-live-answers.md](../ops/p0-go-live-answers.md) |
| NA1 | OS / yerləşdirmə | NetAdmin — açıq |
| NA3 | LAN/VPN giriş modeli | NetAdmin — açıq |
| NA7 | NTP | NetAdmin — açıq |
| NA9 | Offline update | NetAdmin — açıq |

---

## 5. AxTrax yazma

**Qərar:** read-only sync + dedupe/cursor kifayətdir. Kart/qonaq **write** yalnız vendor təsdiqindən sonra ayrıca layihə.

---

## 6. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M12-1 | Flow smoke tests | test |
| M12-2 | Outbox/file fail behaviour | test |
| M12-3 | seed_demo prod block | test |
| M12-4 | AxTrax duplicate skip | test |
| M12-5 | NetAdmin siyahısı sənəddə | bu fayl |
