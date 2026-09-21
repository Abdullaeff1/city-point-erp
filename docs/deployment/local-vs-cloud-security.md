# Lokal vs Cloud — City Point tövsiyəsi və təhlükəsizlik analizi

**Tarix:** 2026-09-21  
**Auditoriya:** rəhbərlik, IT, go-live qərarı  
**Bağlı sənədlər:** [air-gapped-lan.md](./air-gapped-lan.md), [network-checklist.md](../security/network-checklist.md), [phase0-security-audit.md](../security/phase0-security-audit.md)

---

## 1. Qısa qərar (executive summary)

| Sual | Cavab |
|------|--------|
| **Hansı daha yaxşıdır?** | **Lokal (binada / LAN)** — City Point üçün tövsiyə olunan əsas model |
| **Hansında security daha yüksəkdir?** | **Bu layihənin şərtlərində lokal** — attack surface kiçikdir, AxTrax və PII evdə qalır |
| **Cloud heç vaxt?** | İndi əsas platforma kimi **yox**. Sonra: yalnız ehtiyat nüsxə, staging və ya (ayrıca) public website |

**Səbəb bir cümlədə:** Sistem AxTrax turniket DB-sinə LAN üzərindən bağlıdır, go-live-də Internet tələb olunmur və qonaq/işçi PII binadan çıxmamalıdır. Cloud bu üç şərtlə toqquşur.

---

## 2. City Point reallığı (müqayisənin bazası)

Bu sistem adi “İnternet SaaS” deyil. Aşağıdakılar qərarı dəyişir:

1. **AxTraxNG** (`AxTrax1` MS SQL) eyni binanın LAN-ındadır (`172.31.x.x`). ERP oxuma/poller buraya bağlıdır.
2. **Go-live modeli air-gapped / LAN-only** — CDN, public SMTP, Docker Hub runtime asılılığı olmamalıdır.
3. **PII və əməliyyat məlumatı:** şəxsiyyət seriya №, qonaq jurnalı, kart/turniket hadisələri, şirkət ticket-ləri.
4. **İstifadəçilər:** reception, security, FM, rezident portal — əsasən ofis/LAN daxilində.
5. **Qonaq kartı (QONAQ access group)** planı da AxTrax hadisə axınına bağlıdır; VPN kəsilməsi = avtomatik çıxış dayanır.

```text
                    City Point binası
  ┌─────────────────────────────────────────────┐
  │  Staff / Resident PC (LAN)                  │
  │            │                                │
  │            ▼                                │
  │     ERP + Portal + Postgres                 │
  │            │                                │
  │            ▼                                │
  │     AxTrax MS SQL (RO) + turniket           │
  └─────────────────────────────────────────────┘
         ▲
         │  Internet (go-live-də tələb olunmur)
```

---

## 3. Lokal (on-prem / LAN) — ətraflı

### 3.1 Müsbət tərəflər

| Sahə | İzah |
|------|------|
| **Data residency** | Postgres, backup, loglar binada / öz NAS-ınızda qalır. Üçüncü ölkə provider riski yoxdur. |
| **AxTrax uyğunluğu** | Eyni LAN, aşağı latency, VPN yox. Poller Scheduled Task ilə sabit işləyir. |
| **Attack surface** | Public Internetə açıq portal/ERP yoxdursa, dünya üzrə skaner/bot hücumları demək olar ki, yoxdur. |
| **Air-gap** | Uplink kəsiləndə də reception, ticket, (LAN daxilində) AxTrax sync işləyə bilər. |
| **Müqavilə / audit** | “Məlumat binadan çıxmır” demək asandır; kirayəçi şirkətlər üçün inam artım. |
| **Nəzarət** | Patch vaxtı, kim admin-dir, firewall qaydaları — sizin əlinizdədir. |
| **Qiymət modeli** | Aylıq cloud bill yox; bir dəfəlik server + elektrik + IT vaxtı. |

### 3.2 Mənfi tərəflər

| Sahə | İzah |
|------|------|
| **Fiziki risk** | Yanğın, oğurluq, disk/UPS sıradan çıxması — cloud region copy yoxdursa məlumat itə bilər. |
| **Ops yükü** | Yeniləmə (OS, Docker, Django), monitoring, sertifikat — IT komandanın işidir. |
| **Backup intizamı** | Test edilməmiş backup = təhlükəsizlik illüziyası. |
| **Uzaq dəstək** | Evdən düzəliş üçün VPN lazımdır; zəif VPN = yeni risk. |
| **HA / DR** | İkinci server, avtomatik failover — əlavə investisiya tələb edir. |
| **İnsan faktoru** | Zəif parol, share-də `.env`, açıq RDP — lokalı da sındırır. |

### 3.3 Lokal üçün “təhlükəsiz” olmaq şərtləri

Lokal **avtomatik** təhlükəsiz deyil. Minimum:

- `DEBUG=0`, güclü `DJANGO_SECRET_KEY`, `SEED_DEMO=0`
- Postgres yalnız Docker/private şəbəkədə; `5432` public deyil
- AxTrax login **SELECT-only**
- Encrypted NAS backup + **ildə/ayda restore drill**
- `CP_OFFLINE=1`, CDN yox
- Staff VLAN / Portal VLAN (mümkünsə) ayrımı
- Admin və ERP uzaqdan yalnız VPN + MFA ilə

---

## 4. Cloud (AWS / Azure / GCP və s.) — ətraflı

### 4.1 Müsbət tərəflər

| Sahə | İzah |
|------|------|
| **İnfrastruktur möhkəmliyi** | Disk fail, AZ, managed Postgres, snapshot — provider çoxunu edir. |
| **DDoS / WAF** | Public API üçün hazır alətlər. |
| **Coğrafi backup** | Bina yanarsa cloud nüsxə sağ qala bilər. |
| **Uzaq əlçatanlıq** | Portal İnternetdən TLS ilə açıla bilər. |
| **Monitoring** | Mərkəzi log, alert, secret manager. |
| **Scale** | Trafik artsa (City Point üçün az ehtimal) asan böyümək. |

### 4.2 Mənfi tərəflər (bu layihə üçün ağır)

| Sahə | İzah |
|------|------|
| **AxTrax körpüsü** | Cloud app → LAN SQL üçün daimi site-to-site VPN / private link. VPN düşəndə IN/OUT, qonaq OUT, poller dayanır. |
| **Hybrid mürəkkəblik** | İki perimeter (cloud + LAN) = daha çox misconfig, daha çətin audit. |
| **Data çıxışı** | PII və turniket jurnalı provider infrastrukturunda; DPA, kim oxuya bilər, jurisdiksiya. |
| **Public attack surface** | Domain açıqdırsa brute-force, credential stuffing, bot, CVE skan artır. |
| **Internet asılılığı** | Bina uplink kəsiləndə cloud + lokal AxTrax birlikdə işləmir. |
| **Qiymət + lock-in** | Aylıq xərc; çıxmaq baha və vaxt aparır. |
| **Air-gap go-live ilə ziddiyyət** | Sənədləşdirilmiş “no Internet at go-live” modeli pure cloud ilə uyğun gəlmir. |

### 4.3 “Cloud daha təhlükəsizdir” mifi

Böyük cloud-lar **fiziki data center** və patch intizamında güclüdür. Amma:

- Sizin **tətbiq konfiqi** (IAM, security group, açıq admin) səhvdirsə, risk lokalı keçə bilər.
- **Insider / provider admin** riski lokalda yoxdur (və ya fərqli formadadır).
- **AxTrax traffic** internet/VPN üzərindən gedirsə, yeni ələ keçirmə nöqtəsi yaranır.

---

## 5. Hansında security daha yüksəkdir?

### 5.1 Ümumi cavab (City Point şərtləri)

| Risk kateqoriyası | Lokal (düzgün qurulub) | Cloud (app + AxTrax VPN) | Qalib |
|-------------------|------------------------|---------------------------|--------|
| İnternetdən mass-skan / bot | Çox aşağı | Yüksək–orta (WAF ilə orta) | **Lokal** |
| AxTrax / turniket kəsilməsi və ya ələ keçirilməsi | Aşağı (yalnız LAN) | Orta–yüksək (VPN tunnel) | **Lokal** |
| PII-nin ölkə/provider xaricində saxlanması | Yox | Var | **Lokal** |
| Fiziki fəlakət (yanğın) | Yüksək (backup yoxdursa) | Aşağı | Cloud (yalnız DR üçün) |
| Provider/admin sızması | Yox | Var | **Lokal** |
| Konfiq səhvi | Orta | Orta–yüksək | Berabər / prosesə bağlı |
| İçəridən sui-istifadə (staff) | Eyni (RBAC) | Eyni | Berabər |

**Nəticə:** City Point ERP/Portal/AxTrax inteqrasiyası üçün **təhlükəsizlik balansı lokalın xeyrinədir**, bir şərtlə: backup + patch + LAN firewall ciddi aparılsın.

Cloud-un təhlükəsizlik üstünlüyü əsasən **disaster recovery** və **public-facing WAF** sahəsindədir — bunları lokalda da (NAS offsite copy, reverse proxy) qismən əldə etmək olar.

### 5.2 Tövsiyə olunan hədəf arxitektura

```text
PRIMARY (təhlükəsiz + uyğun):
  Lokal ERP/Portal/Postgres + AxTrax LAN + encrypted NAS backup

OPTIONAL LATER:
  - Offsite encrypted backup copy (USB vault / ikinci sayt) — “cloud app” deyil
  - Staging cloud (anonim/demo data)
  - Public marketing site ayrıca; CRM ingest yalnız VPN/LAN ilə
  - Portal eventual public: TLS + yalnız /portal; /erp və /admin VPN-only
```

---

## 6. Mümkün hücumlar və qarşısının alınması

Aşağıda həm lokal, həm (əgər açılsalar) cloud/hybrid ssenarilər üçün tipik attack-lər verilmişdir.

### 6.1 Şəbəkə və perimeter

| Hücum | Nədir | Lokal | Cloud / hybrid | Müdafiə |
|-------|--------|-------|----------------|---------|
| **Port skan / Internet exploit** | Açıq 80/443/5432/22 axtarılır | Risk aşağı (NAT/firewall) | Risk yüksək | Public-də yalnız lazım olan port; Postgres/AxTrax **heç vaxt** public; fail2ban / rate limit |
| **DDoS** | Trafiki boğmaq | Nadirdir | Real risk | Lokal: ISP/null; Cloud: WAF/Shield; mümkün qədər ERP-ni public etmə |
| **VPN brute / zəif VPN** | Uzaq girişin sınması | VPN varsa risk | Site-to-site kritik | MFA, certificate VPN, split tunnel məhdud, monitor failed logins |
| **Man-in-the-middle (LAN)** | Eyni Wi‑Fi/kabeldə dinləmə | Mümkün | VPN üzərində də | HTTPS daxili sertifikat; guest Wi‑Fi-ni staff VLAN-dan ayır; AxTrax yalnız trusted subnet |

### 6.2 Autentifikasiya və hesab

| Hücum | Nədir | Müdafiə |
|-------|--------|---------|
| **Credential stuffing / brute-force login** | Oğurlanmış parol siyahısı ilə `/login/` | Güclü parol (min 10), rate limit, lockout, (mümkünsə) MFA admin üçün; invite-only portal (public signup yox) |
| **Session hijacking** | Oğurlanmış session cookie | `DEBUG=0` secure cookies; HTTPS; qısa session (8 saat); XSS-ə qarşı CSP/escaping |
| **Privilege escalation** | Reception → Admin | RoleRequiredMixin / RBAC; admin hesablarının azlığı; audit log |
| **Demo/default parollar** | `admin123` prod-da | `SEED_DEMO=0`; prod-da demo user yox; README demo yalnız dev |
| **Password reset abuse** | Email ilə hesab yoxlama | Reset siyasətini sərtləşdirmək; internal mail və ya əl ilə invite |

### 6.3 Tətbiq (Django / Portal / ERP)

| Hücum | Nədir | Müdafiə |
|-------|--------|---------|
| **CSRF** | Saxta forma POST | Django CSRF middleware (aktiv saxla) |
| **XSS** | Script injection template-ə | Template auto-escape; user HTML render etmə |
| **IDOR / company leak** | Başqa şirkətin ticket/qonaqına baxmaq | Portalda `resident_company` scope; announcement scopes; staff rolları limit |
| **Admin exposure** | `/admin/` public | Yalnız LAN/VPN; reverse proxy-də blok |
| **File upload abuse** | Zərərli PDF/şəkil | Tip/ölçü validasiyası; upload-u web root-dan kənar saxla |
| **API abuse** | Public stub / reception API | Auth + permission; rate limit; public API key (əgər açılsa) |

### 6.4 Məlumat bazası və inteqrasiya

| Hücum | Nədir | Müdafiə |
|-------|--------|---------|
| **Postgres exposure** | İnternetdən `5432` | Yalnız private Docker network; firewall deny |
| **AxTrax write / sabotage** | Yanlış hesabla kart silmək | **ReadOnly** SQL user; write yox; sync yalnız City Point Postgres-ə |
| **Poller host compromise** | Sync maşını ələ keçirilir | Least privilege OS user; credentials env-də; host hardening; yalnız lazım olan outbound |
| **Backup oğurluğu** | NAS-dakı dump | Backup encryption; backup user ≠ `cp_app`; məhdud share ACL |
| **SQL injection** | ORM bypass | Django ORM; raw SQL-dən qaçın; input validate |

### 6.5 Insider və fiziki

| Hücum | Nədir | Müdafiə |
|-------|--------|---------|
| **Staff sui-istifadə** | Qonaq/FIN/kart məlumatına baxmaq | `reception.view_sensitive_data` kimi field permission; audit; least privilege roles |
| **USB / server otağı** | Fiziki giriş | Kilidli otaq; kamera; disk encryption (mümkünsə) |
| **Social engineering** | “IT-yəm, parolu ver” | Proses: heç kim şifrəni chat-də verməsin; invite yalnız admin |

### 6.6 Cloud-a xas əlavə risklər

| Hücum | Müdafiə (əgər cloud istifadə olunarsa) |
|-------|----------------------------------------|
| Səhv Security Group (0.0.0.0/0 → DB) | Infrastructure as code review; periodic audit |
| Oğurlanmış cloud API key | Short-lived keys, MFA on console, least IAM |
| Misconfigured S3/blob public | Block public ACLs; encryption at rest |
| VPN tunnel down → stale access state | Alert on poller health; fail-closed for auto-checkout assumptions |

---

## 7. Müqayisə cədvəli (ümumi)

| Meyar | Lokal LAN | Public Cloud app | Hybrid (cloud app + LAN AxTrax) |
|-------|-----------|------------------|--------------------------------|
| Go-live Internet-siz | Uyğun | Uyğun deyil | Zəif |
| AxTrax sabitliyi | Ən yaxşı | Pis (remote) | Orta (VPN asılı) |
| İnternet hücum səthi | Kiçik | Böyük | Orta–böyük |
| PII nəzarəti | Ən yaxşı | Zəif–orta | Orta |
| DR / yanğın | Backup-dan asılı | Güclü | Orta |
| Ops sadəliyi | Orta | Orta | Ən çətin |
| Aylıq xərc | Aşağı–orta | Orta–yüksək | Yüksək |
| **City Point tövsiyəsi** | **Əsas** | Tövsiyə edilmir | Yalnız xüsusi ehtiyac |

---

## 8. Tövsiyə olunan təhlükəsizlik checklist (lokal prod)

### Mütləq

- [ ] Tətbiq və Postgres yalnız LAN; Internet uplink olmadan smoke test keçib
- [ ] `CP_ENV=production`, `CP_OFFLINE=1`, `DEBUG=0`, güclü secret
- [ ] `SEED_DEMO=0`, demo parollar yox
- [ ] AxTrax RO credential; write yox
- [ ] Poller Scheduled Task + health admin-də görünür
- [ ] Encrypted backup + restore ən azı bir dəfə sınağıb
- [ ] `/admin/` və ERP uzaqdan açıq deyil (və ya yalnız VPN)
- [ ] Secrets git-də yox (`.env` ignore)

### Güclü tövsiyə

- [ ] Staff / Portal VLAN ayrımı
- [ ] Login rate limit
- [ ] Admin üçün MFA (VPN və ya SSO)
- [ ] Internal NTP (domain DC)
- [ ] Aylıq patch pəncərəsi (USB/internal mirror)
- [ ] Audit: kim qonaq/kart/sensitive baxır

### Sonra (opsional)

- [ ] Offsite encrypted backup copy (cloud *storage* — cloud *app* deyil)
- [ ] Public Portal ayrıca host + TLS; ERP VPN-only
- [ ] WAF yalnız public Portal üçün

---

## 9. Nəticə

1. **Əsas platforma: lokal LAN** — təhlükəsizlik, AxTrax, air-gap və PII baxımından City Point üçün ən düzgün seçimdir.
2. **Security lokalda daha yüksəkdir**, çünki attack surface kiçikdir və kritik inteqrasiya İnternet/VPN-ə bağlı deyil — **əgər** backup, firewall və patch intizamı varsa.
3. **Ən təhlükəli ssenari** “tələsik cloud + AxTrax VPN + zəif konfiq”dir: həm public hücum, həm tunnel riski, həm mürəkkəblik.
4. **Hücumların əksəriyyəti** parol, yanlış açıq port, backup oğurluğu və içəridən həddindən artıq icazə ilə gəlir — bunları proses + checklist bağlayır.
5. Cloud-u **əsas ERP** kimi yox; ehtiyac olsa **ehtiyat nüsxə və ya gələcək public portal** kimi düşünün.

---

## 10. Əlaqəli sənədlər

- [Air-gapped / LAN deployment](./air-gapped-lan.md)
- [Offline smoke checklist](./offline-smoke-checklist.md)
- [Network checklist](../security/network-checklist.md)
- [Phase 0 security audit](../security/phase0-security-audit.md)
- [Database isolation](../security/database-isolation.md)
- [Environments](./environments.md)
