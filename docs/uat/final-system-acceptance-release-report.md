# City Point ERP — Final System Acceptance buraxılış hesabatı

**Tarix:** 2026-11-23  
**Mühit:** lokal Docker (`bin/dev/docker-compose.yml`), sintetik məlumat  
**Qərar (bu mərhələ):** **READY FOR ON-SITE UAT**  
**Qərar deyil:** production deploy / canlı maliyyə yazısı / fiziki kart dəyişikliyi

---

## 1. Kandidat kimliyi

| Sahə | Dəyər |
|------|--------|
| Git baza revisiya | `561ee9f0ff11cccd750223cc6894899c145ef687` (`561ee9f`) |
| Working tree | Phases 10–13 + FSA dəyişiklikləri **commit edilməyib** (kandidat = baza + bu ağac) |
| Branch | `main` (origin/main ilə eyni baza; lokal dəyişikliklər əlavə) |
| DB | PostgreSQL `citypoint` (`django.db.backends.postgresql`) |
| Media | `/app/var/private_media` (özəl) |
| Profil | `CP_ENV=development`, `DEBUG=True`, `TIME_ZONE=Asia/Baku`, `CP_OFFLINE=False` |
| Migrate | `manage.py migrate --check` — təmiz (pending yox) |
| Kredensial / şəxsi məlumat | Hesabatda yoxdur |

### Yoxlama əmrləri

```bash
# Fokus FSA (14 test)
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test apps.core.tests.test_final_system_acceptance --verbosity=1 --keepdb

# Tam suite
docker compose -f bin/dev/docker-compose.yml exec -T web \
  python manage.py test --verbosity=1 --keepdb
```

### Test nəticələri (yenilənmiş qaçış, 2026-11-23)

| Suite | Tapıldı | Nəticə | Müddət |
|-------|---------|--------|--------|
| FSA fokus | 14 | **OK** | ~14 s |
| Tam suite | **791** | **OK** | ~646 s |

*(Phase 13 hesabatında 777 qeyd olunmuşdu; bu kandidatda 791 — əlavə Phase 10–13/FSA testləri daxil.)*

---

## 2. Yeddi axın — hökm və sübut

Hər axın üçün: **lokal nümayiş** / **xarici simulyasiya** / **çatışmayan** / **on-site gözlənilən**.

### Axın 1 — Yeni rezident

| | |
|--|--|
| **Hökm** | Manual Sales yolu lokal nümayiş olunub; website intake **defer** |
| Lokal | Lead (manual) → lease draft → aktivləşmə → aylıq charge generator |
| Simulyasiya / defer | Public website intake — LAN/VPN olmadan təxirə; optional `PUBLIC_API_KEY` |
| On-site | Sales 1.1–1.4; website qərarı Sales/IT (1.5) |
| Sübut | `test_flow1_new_resident_manual_sales_path` |

### Axın 2 — Rezident əməkdaş / giriş

| | |
|--|--|
| **Hökm** | Kart sifarişi + tələb olunan səviyyə + şirkət izolasiyası + deaktiv sonrası tarixçə lokal; AxTrax write mock |
| Lokal | `create_employee_card_order` → ticket; `access_level` tələb; AccessEvent saxlanır |
| Simulyasiya | AxTrax RO sync / fiziki emit |
| On-site | Security + NetAdmin 2.1–2.5; tələb vs AxTrax faktiki səviyyə |
| Sübut | `test_flow2_employee_card_request_and_axtrax_readonly` |

### Axın 3 — Qonaq

| | |
|--|--|
| **Hökm** | Pre-register lokal; QONAQ/reader **on-site NetAdmin** |
| Lokal | `pre_register_visit` |
| Simulyasiya | Delayed/replay OUT, kart reuse — əvvəlki Phase 6 testləri + on-site vərəq |
| On-site | Reception 3.1–3.3; NetAdmin 3.4 + `workflow-a-qonaq-live-acceptance.md` |
| Sübut | `test_flow3_visitor_preregister` |

### Axın 4 — Texniki problem

| | |
|--|--|
| **Hökm** | Ticket → WO → material issue → tamamlanma lokal uzlaşdırılıb |
| Lokal | Portal ticket → WO → StockMovement ISSUE → COMPLETED; qty uzlaşması |
| On-site | Desk/FM/Anbar/Rezident 4.1–4.4 |
| Sübut | `test_flow4_ticket_wo_stock_issue` |

### Axın 5 — Kommersiya sorğusu

| | |
|--|--|
| **Hökm** | Manual CRM handoff; ticket kodu lead note-da saxlanır |
| Lokal | COMMERCIAL ticket → CRM lead `initial_note` ticket kodu ilə |
| On-site | 5.1–5.3 (lease/amendment yolu operatorla) |
| Sübut | `test_flow5_commercial_request_preserves_ticket` |

### Axın 6 — Satınalma

| | |
|--|--|
| **Hökm** | PR→PO→stock işlək; **ilk çatışmayan əlveriş:** PO/receive → supplier invoice → AP JE |
| Lokal | Low-stock PR; `code_for("ap")=="200"` mövcud amma procurement JE yoxdur |
| Çatışmayan | Payable/subledger yazısı — biznes təsir: satınalma stokda bitir, mühasibat AP-də avtomatik yox |
| Sahib | **Finance** (defer və ya implementasiya qərarı) |
| On-site | 6.1–6.3 keçir; 6.4 Finance imzası və ya yazılı defer |
| Sübut | `test_flow6_procurement_stops_before_ap` |

### Axın 7 — İcarə billing / inkasso

| | |
|--|--|
| **Hökm** | 1000 / 400 / 600 AZN lokal tam; GL post portal qalığını **yenidən azaltmır** |
| Lokal | Charge→invoice→confirm→JE post→ödənişlər→TB/report; balance 600→0 yalnız payment ilə |
| On-site | Mühasib/Management 7.1–7.4; real CoA Finance qəbulu |
| Sübut | `test_flow7_lease_billing_1000_400_600_gl_and_report` |

---

## 3. Hesabat sərhədləri A–D

| | Hökm | Sübut |
|--|------|--------|
| **A** Tarixi rezervasiya | `created_at` hold gate: 20.11 boş, 30.11 reserved, 01.12 occupied; erkən hold sayılmır → `skipped_not_yet_recorded` | `test_A_…` |
| **B** Snapshot vs rekonstruksiya | Capture tarixi/vaxtı UI-də; əksik capture «capture edilməyib» | `test_B_…` |
| **C** Debitor mapping | Default AR rol kodu; `ACCOUNTING_ROLE_CODES` ilə alternativ (məs. 115) işləyir; real CoA Finance-dən asılı | `test_C_…` |
| **D** Export / KPI | Eyni cutoff KPI = Excel bundle; stock current-only; occupancy unavailable ≠ 0 | `test_D_…` |

---

## 4. Lokal əməliyyat hazırlığı

| Yoxlama | Nəticə |
|---------|--------|
| Offline static (login CDN yox) | Pass — Google Fonts / jsDelivr / unpkg yox; lokal Lucide |
| AxTrax down ikən ERP | Pass — reports 200, STALE göstərilir |
| Migrate --check | Pass |
| Scheduler / poller | Dev: `AXTRAX_POLL_ON_START`; lease activation missed-poll idempotent (CRM workflow test); snapshot `capture_exec_snapshots`; **prod Task Scheduler / recovery SLA — NetAdmin** |
| Backup dump (izolə fayl) | `var/acceptance_pg_dump_rehearsal.sql` ~478 MB, elapsed dump ~73 s, timestamp **2026-11-23 09:33:22 +04** |
| Disposable restore | DB `citypoint_fsa_restore` yaradıldı → restore ~**22.5 s** → saylar canlı ilə eyni (leases=1, invoices=2, docs=5, je=0) → DB **silindi**. Canlı `citypoint` toxunulmadı |
| Media restore | Private media tam kopya+permission drill **NetAdmin**-ə qalıb (bu qaçışda yalnız Postgres) |
| RTO hədəfi | Təsdiqlənməyib — sahibi: NetAdmin |

---

## 5. On-site UAT vərəqi

Fayl: [`docs/uat/final-system-acceptance-onsite.md`](final-system-acceptance-onsite.md)  
Hər açıq sətir: operator, başlanğıc, əməliyyat, gözlənilən, sübut, nəticə/imza boş.  
QONAQ/reader → NetAdmin+Security; CoA/VAT/deposit/AP → Finance; digər axınlar → müvafiq operatorlar.  
**Yerli Pass ≠ on-site imza.**

---

## 6. Təsdiqlənmiş düzəlişlər (bu kandidatda)

- Phase 11–13 billing / GL / BI sərhədləri + FSA fokus testləri
- Tarixi hold üçün `Lease.created_at` gate; m11 property test uyğunlaşdırıldı
- AR mapping `ACCOUNTING_ROLE_CODES` override
- Snapshot honesty UI («Capture vaxtı» / «capture edilməyib»)
- Suite: əvvəl 1 FAIL (`available_count`) → düzəldildi → **791 OK**

---

## 7. Mərhələ hökməri

| Mərhələ | Hökm |
|---------|------|
| Lokal development readiness | **READY** (791 OK, migrate təmiz, FSA 14 OK) |
| On-site UAT | **READY FOR ON-SITE UAT** — imzalar açıq |
| Finance qəbulu | **AÇIQ** — real CoA, VAT, deposit, opening, AP defer/qəbul |
| NetAdmin readiness | **AÇIQ** — TLS, poller service, offline LAN, disposable restore, rollar |
| Production deployment | **BLOCKED** — on-site + Finance + NetAdmin imzaları olmadan |

---

## 8. Prioritet açıq siyahı

| # | Maddə | Sahib | Tələb olunan sübut | Release təsiri |
|---|-------|-------|--------------------|----------------|
| 1 | On-site 7 axın imzaları | Operatorlar | Doldurulmuş UAT vərəqi | UAT bağlanması |
| 2 | Real CoA + AR mapping + VAT/deposit | Finance | Import + TB uzlaşması | Deploy blocker (statutory) |
| 3 | AP path qəbul və ya yazılı defer | Finance | 6.4 / H5 imza | Launch defer OK yalnız yazılı qərarla |
| 4 | QONAQ + reader direction | NetAdmin/Security | Live vərəq | Axın 3 Pass |
| 5 | AxTrax poller Scheduled Task + health | NetAdmin | `axtrax_sync_status` yaşıl | Ops blocker |
| 6 | Disposable backup+restore (DB+media) | NetAdmin | Restore vaxtı + link/PDF/total yoxlama | Ops blocker |
| 7 | Website intake defer qərarı | Sales/IT | Yazılı defer və ya LAN path | Axın 1.5 |
| 8 | Working tree commit / tagged RC | Dev lead | Təmiz tag + changelog | İzlənilən buraxılış |
| 9 | AxTrax write | Vendor/NetAdmin | API təsdiqi | Şüurlu v1 defer |

---

## 9. Yekun tövsiyə

**READY FOR ON-SITE UAT.**  
Lokal mühəndislik qəbulu tamamlanıb (791 test, yeddi axın + A–D sərhədlər).  
**READY FOR DEPLOYMENT deyil** — Finance, NetAdmin və operator imzaları, həmçinin disposable restore drill gözlənilir.  
Lokal test nəticələri on-site imza və ya production təsdiqi kimi istifadə edilməməlidir.
