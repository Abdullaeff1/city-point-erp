# M1 — Party/Person ↔ Resident* uyğunluq, dublikat, keçid

**Status:** M1 icra sənədi (cutover yox)  
**Tarix:** 2026-11-17  
**Əlaqə:** [party-space-lease-model.md](party-space-lease-model.md) §7, [phase0-data-ownership.md](../data-model/phase0-data-ownership.md), TD-01

---

## 1. Uyğunluq xəritəsi

### 1.1 Party ↔ ResidentCompany

| Party | ResidentCompany | Sync |
|-------|-----------------|------|
| `legacy_resident_company` (OneToOne) | `party` reverse | Körpü açarı |
| `legal_name`, `brand_name` | `name` | Bəli |
| `tax_id` | `voen` | Bəli |
| `contact_email` | `contact_email` | Bəli |
| `contact_phone` | `phone` | Bəli (M1: sync əlavə) |
| `status` active/inactive | `status` active/inactive | Qismən (prospect/blocked yalnız Party) |
| `party_type=organization` | — | Məcburi |
| — | slug, portal_active, is_internal, legal/bank/manager, contract_* | Yalnız company |

### 1.2 Person ↔ ResidentEmployee

| Person | ResidentEmployee | Sync |
|--------|------------------|------|
| `legacy_employee` (OneToOne) | `person` reverse | Körpü |
| `full_name` | `full_name` | Bəli |
| `party` | `company` → Party | Bəli |
| `is_active` | `is_active` | Bəli |
| `person_kind=resident_employee` | — | Məcburi |
| `email` / `phone` / `user` | (employee-də yox) | Sync yox |
| — | card_number, access_level, card_order_*, id_document | Yalnız employee |

### 1.3 Yazma yolları (cari)

| Yol | İstiqamət | Fayl |
|-----|-----------|------|
| `PartyService.upsert_from_resident_company` | Company → Party | `apps/parties/services.py` |
| `save_resident_company` → eyni upsert | ERP yazısı | `apps/residents/company_sync.py` |
| `party_for_company` / `person_for_employee` | Lazy ensure | `apps/parties/resolvers.py` |
| `sync_parties` | Bulk | `apps/parties/management/commands/sync_parties.py` |
| CRM prospect Party | Party (legacy yox) | `apps/crm/services.py` |

**Qayda (M1):** Company → Party üçün tək implementasiya = `PartyService.upsert_*`.  
`company_sync` birbaşa Party field patch etmir — upsert çağırır.

### 1.4 Oxuma SoT (modul üzrə)

| Modul | FK / oxu | SoT indi | Hədəf (cutover sonra) |
|-------|----------|----------|------------------------|
| CRM, Lease, Billing, Parking, Procurement | Party | **Party** | Party |
| Portal User, Tickets, Documents, Reception | ResidentCompany / Employee | **Resident\*** | Party/Person + rol |
| Access / AxTrax | ResidentEmployee | **ResidentEmployee** | Person + ExternalIdentity |
| Occupancy | Lease.party; `Space.resident` bridge | Lease + bridge | Lease only (TD-02) |

---

## 2. Dublikat aşkarlama və birləşdirmə qaydası

### 2.1 Aşkarlama (hesabat — silmə yox)

Komanda: `manage.py report_party_duplicates`

| Tip | Açarı | Qrup |
|-----|-------|------|
| Company VÖEN | `normalize(voen)` boş deyilsə | Eyni voen → ≥2 ResidentCompany |
| Party tax_id | `normalize(tax_id)` | Eyni tax_id → ≥2 Party |
| Ad (zəif) | `normalize(name)` lower/strip | Eyni ad, fərqli voen — əl ilə |
| Orphan Party | `legacy_resident_company` null + rol resident və ya lease/invoice | Prospect və ya körpü qırığı |
| Company without Party | ResidentCompany, Party yox | Sync boşluğu |
| Employee / Person | eyni company + eyni `normalize(full_name)` + aktiv | Şübhəli dublikat |

`normalize`: trim, lower (ad), rəqəm/hərf saxla (VÖEN).

### 2.2 Birləşdirmə qaydası (əl ilə / gələcək alət)

**Avtomatik merge yoxdur.** Təsdiq olmadan silmə/FK köçürmə yox.

1. **Winner seçimi (şirkət):** aktiv portal + aktiv lease olan; yoxdursa ən çox FK (ticket/document/employee); bərabərdə ən köhnə `created_at`.
2. **Loser → Winner:** `legacy_resident_company` Party-ləri birləşdir: loser Party-nin Lease/Invoice/Charge/CRM FK-ləri winner Party-yə; sonra loser Party `inactive` + notes.
3. **ResidentCompany loser:** `is_archived=True`, portal off; istifadəçilər/ticket-lər winner-ə əl ilə və ya ayrı skriptlə.
4. **Prospect Party + mövcud company:** eyni VÖEN/ad → `legacy_resident_company` bağla (`party_for_company` / CRM lease complete); ikinci Party yaratma.
5. **Şəxs:** eyni employee kart/AxTrax ID varsa birləşdir; yalnız ada görə avtomatik merge yox.

Sübut: `report_party_duplicates` çıxışı + (gələcək) merge log `audit`.

---

## 3. Mərhələli keçid (big-bang cutover yox)

| Addım | Nə | Cutover? |
|-------|----|----------|
| M1a | Xəritə + dublikat hesabatı + tək sync yolu | Xeyr |
| M1b | Yeni kommersiya yazıları Party; ops Resident* dual-write | Xeyr |
| M1c | Dublikatları əl ilə təmizlə / körpü bağla | Xeyr |
| M2+ | İcazə scope Party və ya company eyni nəticə | Xeyr |
| Sonra (TD-01 Phase 2) | Tickets/Portal/Reception FK → Party; Resident* facade | Bəli, ayrıca layihə |

UAT B6 qalır: **Party cutover bu keçiddə yox.**

---

## 4. Məlumat sahibliyi (təsdiq)

| Domain | Owner app | Yazı xidməti |
|--------|-----------|--------------|
| Party / Person / PartyRole | `parties` | `PartyService` |
| ResidentCompany / Employee | `residents` | `save_resident_company`, card/access services |
| Property / Space | `property` | property services; occupancy Lease-dən |
| Lease | `leases` | `activate_lease`, lifecycle |
| Reception | `reception` | guest visit services |
| Ticket | `tickets` | ticket services |
| WorkOrder | `maintenance` | WO services |
| Charge / Invoice | `billing` | billing services |
| Journal | `accounting` | accounting services |

Qaydalar:

1. Paralel “Company” cədvəli CRM/Lease/Accounting-də yox.
2. Körpü olan yerdə oxu üçün Party üstünlük (kommersiya); portal/ops Resident* qalır.
3. Party-yə birbaşa profil push (Party→Company) ümumi yol deyil — istisna yalnız lease activate portal bayraqları.

---

## 5. Department / Queue / rol

| Konsept | Harada | M1 qərarı |
|---------|--------|-----------|
| `User.role` + `resident_company` | `accounts` | Ops scope SoT |
| RBAC catalog | `rbac` + `sync_parties` seed | İcazə kodları |
| Org tree | `core.org_seed` | City Point şöbələri |
| `TicketDepartment` / queue | `tickets` | Ticket routing; Party ilə qarışmır |

M1: yeni paralel Department cədvəli yox. Vahidləşdirmə = seed + sənəd; M2 obyekt scope: [m2-permissions-resident-scope.md](m2-permissions-resident-scope.md).

---

## 6. Audit və domain event

| Əməliyyat | Audit |
|-----------|--------|
| `save_resident_company` / archive / delete | `resident_company.*` (`source=erp`) |
| `PartyService.upsert_*` (dəyişiklik) | `party.upserted` / `person.upserted` (`source=parties`) |
| Domain `emit` | Default handler → AuditLog `source=domain_event` |

**Event təkrarı:** `emit(..., event_key=...)` eyni prosesdə eyni `(name, event_key)` üçün ikinci emit atlanır (M1). Dayanıqlı yan təsirlər hələ də Notification `event_key` / DB unikallığı ilə qorunmalıdır.

---

## 7. Qəbul meyarları (M1)

| # | Meyar | Pass |
|---|--------|------|
| M1-1 | Uyğunluq xəritəsi bu sənəddə | Bu fayl |
| M1-2 | Dublikat qaydası yazılıb; `report_party_duplicates` işləyir | Komanda + test |
| M1-3 | Cutover yox; dual-write saxlanılır | B6 + bu §3 |
| M1-4 | Sahiblik cədvəli təsdiqli | §4 |
| M1-5 | Tək Company→Party sync yolu | `company_sync` → `PartyService` |
| M1-6 | Upsert audit + `emit` event_key dedupe | Kod + test |

---

## 8. Sübut

| Sübut | Yer |
|-------|-----|
| Bu sənəd | `docs/architecture/m1-party-resident-mapping.md` |
| Dedupe | `apps/parties/dedupe.py`, `report_party_duplicates` |
| Sync unifikasiya | `apps/residents/company_sync.py` |
| Event | `apps/core/events.py` `event_key` |
| Test | `apps/parties/tests/test_dedupe.py`, `test_phase2_core` emit dedupe |
