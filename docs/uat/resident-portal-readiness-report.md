# Rezident Portal — hazırlıq yoxlaması və düzəlişlər

**Tarix:** 2026-11-23  
**Kandidat baza:** `561ee9f` + working tree (Phases 10–13 / FSA / portal fixes)  
**Canlı xidmət:** `http://127.0.0.1:3001` (docker web)  
**Test:** fokus portal readiness + card/drawing **28 OK**; tam suite **798 OK**

---

## Mərhələ hökməri

| Mərhələ | Hökm |
|---------|------|
| Development readiness | **READY** — 798 OK; migrasiya `residents.0018_requested_access_level` |
| Authenticated browser acceptance | **READY (lokal)** — ASBC bütün nav 200; tvinspark A / B / Hamısı scope işləyir; mobile shell görünür |
| Resident rollout (pilot) | **CONDITIONAL** — canlı QONAQ/hardware NetAdmin+Security; faktura PDF/detail siyasəti Finance; website yox |

---

## Prioritet yoxlamalar

| Yoxlama | Nəticə |
|---------|--------|
| Home + şirkət profili (authenticated) | Pass — ASBC və multi-company |
| Scope → siyahı / balans / unread / download | Pass — `portal_scope` + `user_notifications` company_ids |
| Faktura cəmi səhifələmədən kənar; valyuta ayrı | Pass — test 40×AZN + 11×USD; UI qeydi |
| Kart sifarişi izi; istənilən ≠ AxTrax | Pass — `requested_access_level` saxlanır; siyahıda iki sütun |
| Qonaq tarixləri pagination | Pass — `from`/`to` linklərdə; checkout query saxlanır |
| Köhnə bildiriş / rəsm / ləğv olunmuş membership | Pass — drawing result scope filter; download scope-dan kənar 200 deyil |

---

## Portal sahələri

| Sahə | Modul / operator yolu | Təsdiqlənən | Düzəliş | Boşluq | Release |
|------|----------------------|-------------|---------|--------|---------|
| Home | `portal` / — | Scope, ticket/elan preview | — | — | Launch OK |
| Şirkət profili | residents | Scope-dakı şirkətlər | — | — | Launch OK |
| Sahələr + rəsm | property | Request/download ACL | Drawing notif scope filter | Live DXF keyfiyyəti | Launch OK |
| Ticket yarat / cavab | tickets → Desk/FM | Nav + create | — | — | Launch OK |
| Kart sifarişi | residents → Security | Ticket + status | `requested_access_level` | AxTrax write / fiziki emit | Launch OK (RO) |
| Davamiyyət + Excel | residents / integrations | Roster + export | İstənilən/AxTrax sütunları | Live AxTrax | Launch OK |
| Qonaq | reception | Pre-reg + checkout | Pagination/checkout tarix | QONAQ live | On-site |
| Elanlar | comms | Scope filter | — | — | Launch OK |
| Sənədlər | documents | Public_resident + scope | — | — | Launch OK |
| Fakturalar | billing | Siyahı + multi-currency totals | *(Final: detail + official Document PDF)* | Avtomatik PDF layout / portal ödəniş | Policy: Finance — bax final acceptance |
| Prosedurlar | comms | Siyahı + download | — | — | Launch OK |
| Bildirişlər | comms | Scope + unread | Drawing result filter | — | Launch OK |

---

## Təsdiqlənmiş düzəlişlər

1. `ResidentEmployee.requested_access_level` + migration `0018` — AxTrax sync istəniləni silmir  
2. Portal əməkdaş cədvəlində **İstənilən** / **AxTrax** sütunları  
3. `space_drawing_access_result` bildirişləri yalnız cari şirkət scope-unda  
4. Qonaq checkout `from`/`to` saxlanması  
5. Faktura səhifəsində: cəmlər bütün səhifələri əhatə edir; detail/PDF hələ yoxdur (siyasət)

---

## Feature / siyasət (kod düzəlişi deyil)

| Maddə | Sahib | Təsir |
|-------|-------|-------|
| Avtomatik rəsmi PDF layout / portal ödəniş yaratma | Finance | Detail oxu + Document PDF path hazır; layout qərarı açıq — [`resident-portal-final-acceptance.md`](resident-portal-final-acceptance.md) |
| QONAQ membership + reader direction | NetAdmin / Security | Axın 3 on-site |
| AxTrax write (kart grant) | Vendor / NetAdmin | Şüurlu RO defer |

---

## Yoxlama əmrləri

```bash
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test apps.portal.tests.test_portal_readiness --verbosity=1 --keepdb

docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test --verbosity=1 --keepdb
```

**Browser (sintetik):** `office@asbc.az` (tək); `rehber@tvins-park.test` (iki üzvlük — seçim ekranı). Şifrələr yalnız lokal UAT üçündür; hesabatda saxlanılmır.
