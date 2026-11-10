# City Point ERP — Tam Texniki Plan (Hədəf vəziyyət)

| Sahə | Dəyər |
|------|--------|
| Versiya | 1.0 |
| Tarix | 2026-11-05 |
| Auditoriya | Rəhbərlik, NetAdmin/SysAdmin, ERP ops, inkişaf |
| Məqsəd | Bütün modullar hazır olanda sistemin **tam hədəf** texniki planı |
| Əsas | Final Master Plan (Fazalar 0–13) + cari repo (`origin/main`) |
| Deploy | **Mövcud daxili (on-prem) server** — sistem artıq orada qaldırılıb; LAN / air-gapped |

> Bu sənəd **hazırkı MVP-nin inventarı deyil** — CRM, satış, anbar, satınalma, maintenance, billing, muhasibatlıq və BI daxil olmaqla **sistem bitəndə** nəyin necə işləyəcəyini, infrastrukturu, təhlükəsizliyi, qəbul meyarlarını və **xərcləri** bir yerdə toplayır.  
> Cari kodda bəzi kommersiya modulları thin/scaffold səviyyəsindədir; aşağıdakı DoD-lər **tam hazır** məhsul üçün məcburidir.  
> **İnfrastruktur fərziyyəsi:** City Point-in **öz daxili serveri** var və ERP/Portal **artıq orada işləyir**. Yeni server almaq əsas ssenari deyil; xərclər əsasən modul tamamlama, ops və ehtiyat gücləndirmə üçündür.

---

## 1. Vizyon və sərhədlər

### 1.1 Vizyon

City Point üçün vahid **on-prem bina idarəetmə + kommersiya ERP** platforması:

- Rezident portal (sorğu, qonaq, sənəd, plan)
- Staff ERP (əmlak, icarə, CRM/satış, FM, anbar, satınalma, billing, muhasibat)
- Security portal (giriş/çıxış, qonaq jurnalı, kart)
- Reception və Service Desk iş axınları
- AxTrax turniket oxuma inteqrasiyası (LAN)

### 1.2 Daxil (in-scope) — tam bitmiş sistem

| Domen | Modul / funksiya |
|-------|------------------|
| İdentifikasiya | Hesablar, rollar, portal membership, invite |
| Əmlak | Bina, mərtəbə, sahə, aktiv, parkinq, sayğac, DXF/texniki plan |
| Rezident | Şirkət/işçi, kart, access event, sənədlər |
| Reception | Qonaq/vizit lifecycle |
| Service Desk | Ticket taxonomy, routing, SLA, departament ACL |
| Security | Security portal, kart xəbərdarlıqları, floor plan icazəsi |
| İcarə | Lease / LeaseLine, tarif, deposit, indexasiya |
| CRM / Satış | Lead → Opportunity → Offer → Lease |
| Facility Management | Work order, plan, inspection, xərc sətirləri |
| Anbar | SKU, stok, hərəkət, low-stock |
| Satınalma | PR → Approval → PO → RFQ → qəbul → stok |
| DMS / Kargüzarlıq | Sənəd versiyası, private storage, görünürlük |
| Billing | Charge, Invoice, Payment, cərimə/VAT qaydaları |
| Muhasibatlıq | CoA, jurnal, invoice→JE, bağlanış |
| Kommunikasiya | Elan, in-app bildiriş, e-poçt/outbox |
| BI / Hesabat | KPI, eksport, rəhbərlik paneli |
| İntegrasiya | AxTrax RO (+opsional write), Outlook/SMTP, website API |
| Platforma | Audit, RBAC, workflow approval, domain events |

### 1.3 Xaric (out-of-scope) — v1 tam bitmə üçün

- Public cloud SaaS hosting (əsas model on-prem)
- Mobil native app (responsive web kifayətdir; ayrıca mobil v2)
- Tam e-invoicing dövlət gateway (ayrı layihə / adapter)
- AxTrax write-grant — yalnız vendor API təsdiqlənəndə
- Çox-binalı multi-tenant SaaS (City Point tək binadır; Organization ağacı daxili)

---

## 2. Cari vəziyyət vs hədəf

| Sahə | Cari (2026-11) | Hədəf (tam bitmiş) |
|------|----------------|---------------------|
| Portal / Security / Reception / Tickets | REAL (əməliyyatda) | REAL + SLA/taxonomy təsdiqli |
| Əmlak + planlar (Temiz DXF/PNG) | REAL | REAL + bütün sahə foto/meta |
| İcarə / CRM / FM / Anbar / Satınalma / Billing / Accounting | Thin / scaffold | Production DoD (aşağıda) |
| Party cutover | Dual-read | Tək SSOT Party/Person |
| RBAC | Cədvəl + role mixin | Tam PermissionCode enforcement |
| BI | Qismən KPI | Tam hesabat + eksport |
| AxTrax | Read + poller | Read + (opsional) write adapter |

---

## 3. Hədəf arxitektura

### 3.1 Ümumi diaqram (məntiqi)

```text
[Rezident brauzer]──► Nginx ──► Gunicorn/Django ──► PostgreSQL 16
[Staff / Security]──┘              │
                                   ├── var/private_media (plan, sənəd)
                                   ├── AxTrax MS SQL (LAN, RO)
                                   ├── SMTP / file outbox (invite)
                                   └── (opsional) Graph Outlook
```

### 3.2 Texniki yığın (hədəf = cari + sabitləşdirilmiş)

| Qat | Seçim |
|-----|--------|
| Dil / framework | Python 3.12, Django 5.1+ |
| DB | PostgreSQL 16 |
| UI | Server-rendered templates (AZ/EN/RU), Whitenoise static |
| App server | Gunicorn + systemd |
| Reverse proxy | Nginx (TLS, rate limit, private media bağlama) |
| OS | AlmaLinux 10 (native, Docker tövsiyə olunmur prod üçün) |
| CAD | `ezdxf` DXF→SVG; PNG texniki plan |
| İnteqrasiya | `pymssql` (AxTrax), `msal`/`httpx` (Outlook, opsional) |

### 3.3 Tətbiq qatları

1. **Presentation** — `portal`, `erp`, `security` URL shells  
2. **Domain services** — biznes məntiqi views-də deyil, services-də  
3. **Persistence** — Django ORM, PostgreSQL  
4. **Integration adapters** — AxTrax, mail, website  
5. **Cross-cutting** — audit, RBAC, workflows, domain events  

### 3.4 Prinsiplər

1. Hər entity üçün **bir SSOT modul**  
2. İşləyən MVP (Reception/Tickets/Security/AxTrax read) **yenidən yazılmır** — genişləndirilir  
3. Scaffold UI production kimi satılmır  
4. Xarici sxemlər **DO NOT GUESS**  
5. Hər faza qəbul + regression olmadan növbəti başlamır  

---

## 4. İstifadəçi səthləri və rollar

### 4.1 Portallar

| Səth | URL | Kim |
|------|-----|-----|
| Resident Portal | `/portal/` | `resident_user` (+ multi-company membership) |
| Staff ERP | `/erp/` | admin, management, reception, service_desk, property_fm |
| Security | `/security/` | security, admin, management |
| Admin | `/admin/` | superuser / ops |
| API | `/api/` | public stubs + staff reception JSON |

### 4.2 Rollar (hədəf)

| Rol | Əsas iş |
|-----|---------|
| Admin | Konfiq, istifadəçi, tam ACL |
| Management | KPI, təsdiqlər, oxuma |
| Reception | Qonaq/vizit |
| Service Desk | Ticket növbə |
| Property / FM | Sahə, WO, anbar/satınalma əlaqəsi |
| Security | Kart, access, qonaq jurnalı, plan icazəsi |
| Resident | Portal sorğu, qonaq, sənəd, plan sorğusu |
| (Gələcək) Accountant | Billing/JE bağlanış — mövcud role və ya `management` + PermissionCode |

---

## 5. Modul kataloqu və Definition of Done

Hər modul **tam bitmiş** sayılır yalnız DoD yerinə yetəndə.

### 5.1 Platforma və təhlükəsizlik

| Element | DoD |
|---------|-----|
| Accounts | Invite, reset, portal membership, role redirect |
| RBAC | PermissionCode bütün kritik ERP əməliyyatlarında yoxlanır |
| Audit | Create/update/delete + status dəyişikliyi auditdə |
| Workflows | Lease/Offer/PR/sənəd üçün ApprovalRequest işləyir |
| Private media | Plan/sənəd yalnız imzalı/ACL URL ilə |

### 5.2 Əmlak + planlar

- CRUD: Building / Floor / Space / Asset / Parking / Meter  
- Sahə kartında DXF + texniki plan; Temiz mapping import  
- Rezident plan icazəsi (TTL)  
- **DoD:** bütün aktiv ofis sahələrinin planı var; kodlar `space_drawing_map` ilə uyğun  

### 5.3 Rezident + Access

- Şirkət profili, işçi, kart, `portal_active`  
- AccessEvent AxTrax-dan; rematch  
- Kart sifarişi status axını  
- **DoD:** 1–2 pilot şirkət real kart/event görür; AxTrax health yaşıl  

### 5.4 Reception

- Pre-register → waiting → checked-in → out  
- Export / jurnal  
- **DoD:** reception günlük işi ERP-dən; Excel əvəzedici yox  

### 5.5 Service Desk / Tickets

- Taxonomy + RoutingRule → department  
- SLA + calendar  
- Role/department ACL  
- WO-eligible subcategory → Maintenance  
- **DoD:** Security/Service Desk ticket-ləri itmir; SLA hesabatı var  

### 5.6 İcarə (Lease)

- Draft → active → end; LeaseLine (sahə, tarif, SC)  
- Indexasiya, deposit, fit-out  
- Charge generator (aylıq)  
- **DoD:** real icarə qaydaları biznesdən təsdiqli; charge cədvəli düzgün  

### 5.7 CRM / Satış

- Lead → qualify → Opportunity → Offer → Lease  
- ERP ekranlar + təsdiq  
- (Opsional) website lead API  
- **DoD:** satış hunisi rəhbərlik üçün izlənir; offer→lease kəsiksiz  

### 5.8 Facility Management

- WorkOrder status, plan, inspection  
- Material sətirləri → anbar  
- Billable → Charge  
- **DoD:** ticket→WO→bağlanış→billing əlaqəsi işləyir  

### 5.9 Anbar

- SKU, stok, hərəkət, mənfi stok qadağası  
- Low-stock → PR  
- **DoD:** FM material silinməsi stoku azaldır; inventar hesabatı  

### 5.10 Satınalma

- PR → Approval → PO → receive → stock  
- RFQ müqayisə (hədəf)  
- **DoD:** təsdiq matrisi ilə PR/PO; qəbul stoka düşür  

### 5.11 DMS

- Upload, versiya, private storage, `visible_to_resident`  
- **DoD:** portalda yalnız icazəli sənədlər; `/media/documents` 403  

### 5.12 Billing

- Charge / Invoice / Payment / due / cərimə  
- Portal invoice görünüşü (hədəf)  
- **DoD:** aylıq icarə+SC fakturaları; ödəniş qeydi JE yaradır  

### 5.13 Muhasibatlıq

- Real CoA (City Point kodları)  
- `post_journal`; dövr bağlanışı  
- Invoice AR/revenue  
- **DoD:** mühasib aylıq bağlaya bilir; trial balance uyğundur  

### 5.14 Kommunikasiya

- Elan scope (bina/şirkət)  
- In-app + e-poçt/outbox  
- **DoD:** invite və elan çatdırılma yolu təsdiqli (SMTP və ya link)  

### 5.15 BI / Rəhbərlik

- Occupancy, ticket SLA, AR aging, stok, satış hunisi  
- Excel/PDF eksport  
- **DoD:** rəhbərlik həftəlik paneli bir ekrandan  

---

## 6. Məlumat modeli (qısa SSOT)

| Entity | Sahib modul |
|--------|-------------|
| User / Role / Membership | accounts |
| Party / Person | parties (cutover sonrası) |
| Building / Floor / Space / Drawing | property |
| ResidentCompany / Employee / AccessEvent | residents (Party-yə keçid planlı) |
| Visit | reception |
| Ticket / RoutingRule | tickets |
| Lease / LeaseLine | leases |
| Lead / Opportunity / Offer | crm |
| WorkOrder | maintenance |
| Warehouse / SKU / StockMovement | warehouse |
| PR / PO / RFQ | procurement |
| Document | documents |
| Charge / Invoice / Payment | billing |
| Account / JournalEntry | accounting |
| Announcement / Notification | comms |
| ExternalIdentity / SyncLog | integrations |
| AuditLog | audit |
| ApprovalRequest | workflows |

Ətraflı: `docs/data-model/phase0-entity-map.md`, `party-space-lease-model.md`.

---

## 7. İnteqrasiyalar (tam sistem)

| Sistem | Rejim | Qeyd |
|--------|-------|------|
| AxTrax NG MS SQL | LAN RO (məcburi) | Poller systemd/Windows task; write yalnız vendor API ilə |
| SMTP / Exchange | LAN və ya file outbox | `CP_OFFLINE=1` dəstəyi |
| Microsoft Graph Outlook | Opsional | Air-gap-də bağlana bilər |
| Website public API | Opsional / VPN | Lead + public spaces |
| E-invoicing / bank | Gələcək adapter | v1-də əl ilə ödəniş qeydi kifayət |

---

## 8. İnfrastruktur və deploy

### 8.0 Mövcud vəziyyət (fakt)

- Sistem **City Point daxili serverində** qaldırılıb və işləyir (on-prem, bina LAN).
- Prod yeniləmələri: NetAdmin/SysAdmin-ə `citypoint-app.zip` / `CityPoint_NetAdmin_Yenileme_*.zip` + `OXU_MENI.txt` ilə kod + migrate + (lazımysa) import.
- Yeni “sıfırdan server almaq” bu planın əsas CAPEX-i **deyil**; yalnız mövcud host yetərsiz olanda (CPU/RAM/disk/backup) gücləndirmə nəzərdə tutulur.

### 8.1 Hədəf topologiya (mövcud host üzərində)

| Komponent | Spesifikasiya (min. tövsiyə / yoxlama) |
|-----------|----------------------------------------|
| App + DB (mövcud server) | İdeal: 8+ vCPU, 32+ GB RAM, NVMe; yük artanda ölçün |
| OS | AlmaLinux 10 (və ya cari prod OS — NetAdmin rəhbəri ilə uyğun) |
| Backup | Yerli + NAS; gündəlik DB, həftəlik media (drill məcburi) |
| NTP | Daxili domain / lokal NTP |
| Şəbəkə | ERP/Portal VLAN; AxTrax SQL yalnız RO; firewall |

### 8.2 Deploy paketləri

- İlk quraşdırma artıq edilib → bundan sonra **yeniləmə** paketləri  
- `CityPoint_NetAdmin_Yenileme_*.zip` = `citypoint-app.zip` + `OXU_MENI.txt`  
- (Ehtiyat) tam USB: wheelhouse + RPM — yalnız OS/Python asılılıq dəyişəndə  

### 8.3 Ətraf mühitlər

| Env | Məqsəd |
|-----|--------|
| Dev | Developer laptop / Docker `bin/dev` |
| Staging (LAN, tövsiyə) | UAT — eyni daxili şəbəkədə ayrı instance və ya ayrı DB |
| Prod | **Mövcud daxili server** |

---

## 9. Qeyri-funksional tələblər (NFR)

| NFR | Hədəf |
|-----|--------|
| Availability | İş saatlarında 99.5% (LAN) |
| RPO / RTO | RPO ≤ 24 saat; RTO ≤ 4 saat (pilot); prod üçün RPO ≤ 4 saat |
| Concurrent users | ≥ 150 portal + 30 staff eyni anda |
| Dil | AZ default; EN/RU |
| Audit retention | ≥ 24 ay |
| Password | Güclü siyasət; reset ACL |
| Secrets | `.env` git-də yox; fail-closed prod |

---

## 10. Təhlükəsizlik

- Rol əsaslı portal ayrımı (security ERP-yə düşmür və əksinə)  
- Private plan/sənəd storage  
- Postgres ayrı rollar (app vs backup)  
- Nginx: `/media/documents` 403; TLS daxili CA və ya sertifikat  
- AxTrax yalnız SELECT hesabı  
- Air-gapped: outbound Internet yox (siyasətə görə)  
- Periodik: `docs/security/phase0-security-audit.md` checklist  

---

## 11. Implementasiya fazaları (hədəf tamamlanma)

Master Plan ilə uyğun:

| Faza | Ad | Nəticə |
|------|-----|--------|
| 0 | Audit | Sənədləşmə |
| 1 | Hardening | Pilot DoD |
| 2 | ERP Core | Party, approval, events |
| 3 | Property / Lease | Kommersiya əmlak |
| 4 | CRM + Website | Satış hunisi |
| 5 | Resident / Access | Kart + AxTrax |
| 6 | Service Desk | SLA yetkin |
| 7 | FM | WO istehsalı |
| 8 | Warehouse | Anbar |
| 9 | Procurement | Satınalma |
| 10 | DMS | Kargüzarlıq |
| 11 | Billing | Faktura/ödəniş |
| 12 | Accounting | JE / CoA |
| 13 | BI | Rəhbərlik |
| — | Acceptance | 7 kritik axın UAT |

### 11.1 Təxmini müddət (tam DoD-ə qədər)

Fərziyyə: 1–2 backend, 1 fullstack/UI, 0.5 QA/ops, biznes SME əlçatan.

| Blok | Kalendar |
|------|----------|
| Artıq REAL olanların cilalanması + pilot | 4–6 həftə |
| Lease + CRM + Billing dərinləşmə | 8–12 həftə |
| FM + Anbar + Satınalma | 8–12 həftə |
| Accounting + BI + Party cutover | 6–10 həftə |
| UAT / training / hardening | 4–6 həftə |
| **Cəmi (paralel iş ilə)** | **~6–10 ay** |

Kritik yol: biznes qaydaları (SLA, CoA, icarə tarifləri, təsdiq matrisi) gecikərsə müddət uzanır.

---

## 12. Komanda və məsuliyyətlər

| Rol | Məsuliyyət |
|-----|------------|
| Product Owner (City Point) | Prioritet, DoD qəbulu |
| Backend / Fullstack | Modullar, inteqrasiya |
| QA | Regression, UAT skriptləri |
| NetAdmin | Şəbəkə, firewall, AxTrax SQL, TLS |
| SysAdmin | OS, Postgres, Nginx, backup |
| ERP ops | İstifadəçi, seed, elan, pilot |
| Mühasibat / FM / Reception SME | Qaydalar və UAT |

---

## 13. Risklər və mitigasiya

| Risk | Təsir | Mitigasiya |
|------|-------|------------|
| Biznes qaydaları gecikir | Yüksək | `finish-requirements.md` A bölməsi bağlanmadan Phase 3+ dərinləşmə |
| AxTrax write yox | Orta | Read kifayət; write mock qalır |
| Air-gap vs Outlook | Orta | SMTP LAN və ya invite-by-link |
| Party dual-read uzanır | Orta | Cutover plan + `sync_parties` |
| Thin UI “hazır” kimi satılır | Yüksək | Bu planın DoD siyahısı |
| Backup drill edilmir | Yüksək | Aylıq restore test |
| Data migration Excel | Orta | Mapping + dry-run |

---

## 14. Xərclər (təxmini, 2026) — daxili server artıq var

> Qiymətlər **təxmini diapazondur** (AZN).  
> **Əsas ssenari:** daxili server mövcuddur, sistem orada qaldırılıb → **yeni server CAPEX yoxdur** (və ya yalnız ehtiyat gücləndirmə).  
> ƏDV ayrı göstərilməyib; tender üçün yenidən qiymətləndirin.

### 14.1 CAPEX — infrastruktur (opsional / ehtiyat)

Mövcud host kifayətdirsə bu sətirlər **0** ola bilər.

| Maddə | Təxmini (AZN) | Qeyd |
|-------|---------------|------|
| Yeni app/DB server | 0 (əsas) / 8 000 – 25 000 | Yalnız mövcud host yetməyəndə |
| NAS / backup disk əlavəsi | 0 – 8 000 | Backup yoxdursa tövsiyə |
| UPS / disk genişləndirmə | 0 – 4 000 | Ehtiyat |
| TLS / daxili CA | 0 – 800 | Adətən daxili |
| **CAPEX infra (tipik)** | **0 – 12 000** | Çox vaxt yalnız backup/disk |

### 14.2 Layihə — qalan modulların tamamlanması (əsas xərc)

| Maddə | Təxmini (AZN) | Qeyd |
|-------|---------------|------|
| Proqram təminatı (Lease, CRM, FM, Anbar, Satınalma, Billing, Accounting, BI, Party cutover) | 60 000 – 140 000 | 6–10 ay |
| UX / analitika cilalama | 8 000 – 20 000 | |
| UAT, sənədləşmə, istifadəçi training | 6 000 – 15 000 | Mövcud serverdə deploy daxil |
| Data migration / təmizlik | 3 000 – 12 000 | Excel/legacy varsa |
| Contingency 15% | 11 000 – 28 000 | |
| **İnkişaf/tamamlama cəmi** | **~88 000 – 215 000** | |

### 14.3 OPEX — illik (mövcud daxili host)

| Maddə | Təxmini / il (AZN) | Qeyd |
|-------|---------------------|------|
| Server elektrik / otaq (pay) | 500 – 3 000 | Artıq bina xərcinə düşür |
| Support & minor change (0.25–0.5 FTE) | 12 000 – 36 000 | |
| Backup media / yoxlama | 500 – 2 000 | |
| OS/DB patch əməyi (SysAdmin) | 2 000 – 6 000 | |
| Cloud hosting | **0** | On-prem |
| AxTrax lisenziya | 0* | *Mövcud vendor müqaviləsi |
| **OPEX cəmi / il** | **~15 000 – 47 000** | |

### 14.4 Ümumi mənzərə (1-ci il) — daxili server ssenarisi

| | Aşağı | Yuxarı |
|--|-------|--------|
| CAPEX infra (ehtiyat) | 0 | 12 000 |
| Modul tamamlama | 88 000 | 215 000 |
| OPEX il-1 | 15 000 | 47 000 |
| **İl-1 cəmi** | **~103 000** | **~274 000** |

**Praktik planlaşdırma rəqəmi (infra artıq var):** əlavə paket çox vaxt **~90–180 min AZN** (inkişaf + UAT + contingency), üstəgəl illik support.

### 14.5 Xərcə daxil olmayanlar

- AxTrax aparat/lisenziya (ayrı vendor, artıq ola bilər)  
- Dövlət e-invoice / bank API layihəsi  
- Public cloud / SaaS abunə (**yoxdur** — daxili server)  
- Mobil native app  
- Yeni “sıfırdan” server (lazım deyilsə) 

---

## 15. Qəbul meyarları (Production Acceptance)

Sistem **bitmiş** sayılır ki:

1. **7 kritik axın** UAT-dən keçib (regression yox):  
   - Portal ticket → doğru departament  
   - Reception vizit  
   - Security access/kart  
   - Sahə planı yükləmə/icazə  
   - Lead → Offer → Lease → Invoice  
   - Ticket → WO → anbar/satınalma  
   - Invoice → Payment → Journal  
2. Pilot 1–2 rezident şirkət 2 həftə kritik qüsur olmadan işləyir  
3. Backup restore drill uğurlu  
4. AxTrax sync health yaşıl  
5. Bu sənədin modul DoD-ləri imzalanıb  
6. NetAdmin/SysAdmin runbook aktual  

---

## 16. Biznesdən tələb olunan qərarlar

`docs/architecture/finish-requirements.md` ilə eyni — qısaca:

1. SLA + iş təqvimi  
2. İcarə/billing/VAT/cərimə qaydaları  
3. Real CoA  
4. Təsdiq matrisi  
5. Elan siyasəti  
6. Mail yolu (SMTP vs link)  
7. Pilot şirkətlər  

Bunlar olmadan Phase 3–13 **biznes-complete** elan edilə bilməz.

---

## 17. Əlaqəli sənədlər

| Sənəd | Rol |
|-------|-----|
| `docs/architecture/master-plan-progress.md` | Faza statusu |
| `docs/architecture/phase0-*.md` | Audit |
| `docs/architecture/finish-requirements.md` | Qalan məlumatlar |
| `docs/deployment/air-gapped-lan.md` | Offline deploy |
| `docs/deployment/CityPoint_AlmaLinux10_NetAdmin_Tam_Rehberi.docx` | Quraşdırma |
| `docs/integrations/phase0-integration-map.md` | İnteqrasiya |
| `docs/backup/phase1-backup-restore.md` | Backup |
| `docs/security/phase0-security-audit.md` | Təhlükəsizlik |

---

## 18. Növbəti addımlar (tövsiyə)

1. Rəhbərlik bu planı və **xərc diapazonunu** təsdiqləsin  
2. `finish-requirements.md` A+B+C doldurulsun  
3. Qalan DoD üçün sprint backlog (Lease/CRM/Billing prioritet)  
4. Staging-də UAT cədvəli  
5. Hər major yeniləmədə NetAdmin `Yenileme_*.zip` + `OXU_MENI.txt`

---

*City Point ERP — Tam Texniki Plan v1.0 · 2026-11-05*
