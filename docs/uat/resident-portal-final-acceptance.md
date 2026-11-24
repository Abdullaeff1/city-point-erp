# Rezident Portal — Final Acceptance

**Tarix:** 2026-11-23  
**Baseline:** [`resident-portal-readiness-report.md`](resident-portal-readiness-report.md) (798 OK)  
**Bu qaçış:** fokus portal **8 OK** · tam suite **800 OK**

---

## 1. UAT namizədi

| Sahə | Dəyər |
|------|--------|
| Git baza | `561ee9f0ff11cccd750223cc6894899c145ef687` |
| Working tree | Phases 10–13 / FSA / portal readiness + **invoice detail** (commit edilməyib) |
| Migrasiya (UAT/dev DB) | `residents.0018_requested_access_level` → **[X] applied** |
| Xidmət | Docker `citypoint-dev-web-1` → `http://127.0.0.1:3001` |
| Profil | `CP_ENV=development`, `TIME_ZONE=Asia/Baku` |

### Portal dəyişiklik manifesi (bu qəbul)

- `apps/residents/models.py` + `migrations/0018_requested_access_level.py` — istənilən səviyyə
- `apps/residents/services.py`, `admin.py`, `templates/portal/employees.html`
- `apps/comms/links.py` — drawing notif scope
- `apps/portal/views.py`, `urls.py` — invoice detail + official download
- `templates/portal/invoice_detail.html`, `invoices.html`, `guests.html`, `base.html`
- `apps/portal/tests/test_portal_readiness.py`

### Yoxlama

```bash
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py showmigrations residents | findstr 0018

docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test apps.portal.tests.test_portal_readiness --verbosity=1 --keepdb

docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test --verbosity=1 --keepdb
```

---

## 2. Faktura detail vs rəsmi PDF (ayrı deliverable)

| Deliverable | Status | Mənbə / icazə |
|-------------|--------|----------------|
| **Read-only detail** | **İmplementasiya olundu** | `Invoice` + `InvoiceLine` + `Payment`; `invoice_balance` / `invoice_vat_summary`; portal scope `legacy_resident_company_id` |
| **Rəsmi PDF** | **Yalnız bağlanmış sənəd** | `Document` (`invoice` FK, `visible_to_resident`, `PUBLIC_RESIDENT`); generator **yoxdur** |
| Portal ödəniş yaratma | Yox / defer | Ödəniş Finance/ERP `record_payment` + approval |

### Finance — dəqiq suallar (sahib: Finance)

1. **Rəsmi PDF layout:** Sistem avtomatik PDF generasiya etsin, yoxsa mühasib hər ISSUED faktura üçün təsdiqlənmiş PDF-i Documents-ə yükləsin (`invoice` link + portala görünən)?  
2. **Şablon:** Hansı blank/ştamp/ƏDV sətir formatı rəsmidir (nümunə fayl)?  
3. **Portal ödəniş:** Rezident portalda ödəniş sorğusu açılsınmı, yoxsa yalnız Finance qeydi + portal oxu?

İmzalanmamış qərar = rəsmi PDF və portal ödəniş **launch defer**.

---

## 3. Mobile (390×844) — sintetik multi-company

Hesab: `rehber@tvins-park.test` (Tvins + PARK ELMLƏR).

| Addım | Nəticə |
|-------|--------|
| Scope A (PARK) | Pass — sidebar ~72px (icon rail) |
| Yeni müraciət forması | Pass — form görünür |
| Qonaq forması | Pass — form görünür |
| Əməkdaşlar / kart yolu | Pass — səhifə 200 |
| Fakturalar A | Pass — 200 |
| Scope Hamısı | Pass — «Bütün şirkətlər (2)»; profil multi |
| Scope B (Tvins) | Pass — fakturalar 200 |
| Detail/download scope | Unit: A detail digər şirkət fakturasını açmır; official PDF yalnız scope + Document |

*(Canlı DB-də bəzi şirkətlərdə faktura sətiri boş ola bilər — detail unit testlərdə sübut olunub.)*

---

## 4. On-site QONAQ

Vərəq: [`qonaq-onsite-final-acceptance.md`](qonaq-onsite-final-acceptance.md)  
Qonaq kartı / nəzarət kartı / OUT reader / kart reuse / AxTrax↔ERP vaxt / əməkdaş əl emit+RO sync — nəticə sütunları **boş**.

---

## 5. Hökmər

| Mərhələ | Hökm |
|---------|------|
| Development | **READY** (800 OK; 0018 applied; detail shipped) |
| Authenticated / mobile browser (lokal) | **READY** |
| Finance (rəsmi PDF / portal ödəniş) | **AÇIQ** — yuxarıdakı 3 sual |
| NetAdmin / Security QONAQ | **AÇIQ** — on-site vərəq |
| Broader resident rollout | **CONDITIONAL** — Finance qərarı + QONAQ imzaları + RC commit/tag |

### Rollout üçün tələb olunan sübut

1. Tagged RC + `0018` prod/UAT migrate qeydi  
2. Finance yazılı cavab (PDF yolu + şablon)  
3. Doldurulmuş QONAQ vərəqi (A–C)  
4. Pilot şirkət: ən azı 1 ISSUED faktura detail + (əgər qərar yükləmədirsə) 1 official Document PDF  
5. Pilot kart sifarişi: istənilən vs AxTrax səviyyə ekran şəkli
