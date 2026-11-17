# Mərhələ qəbul meyarları və sübut

**Məqsəd:** Hər funksional-hazırlıq mərhələsi üçün (A–E) ayrıca qəbul meyarı və görülən işin sübutunu saxlamaq.  
**Qayda:** Meyar Pass olmadan mərhələ “bağlı / production-hazır” sayılmır. CRM üçün əlavə gate: [phase0-module-status.md](../architecture/phase0-module-status.md).

Operator checklist (Addım-addım UI): [functional-readiness-checklist.md](functional-readiness-checklist.md).

---

## Mərhələ A — CRM checkout və source of truth

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| A1 | Migration ardıcıllığı | `0003` → `0004` → `0005`; forward apply OK |
| A2 | Rollback | Test DB-də `migrate crm 0003` sonra yenidən `0005` OK |
| A3 | Köhnə data | Mövcud outcome/activity pozulmur; orphan activity yox |
| A4 | Avtomatik test | `test_crm_sales` + `test_crm_import` yaşıl |
| A5 | Offer email | Default off; göndərmə `NotificationDispatch` / `send_templated_email`; səssiz `fail_silently` yox |
| A6 | Status sənədi | Modul statusu kodla uyğun; CRM **prod gate** yazılıb |
| A7 | Business qəbul | Satış/CRM yazılı “qəbul” + UAT checklist §A bütün sətirlər Pass |

**A7 olmadan** A mərhələsi production üçün bağlanmış sayılmır (kod branch-də olsa belə).

### Sübut (görülən iş)

| Sübut | Harada |
|-------|--------|
| Commit | `a2599ae` — CRM V2, import, PDF, migrations `0004`/`0005` |
| Test | `apps/crm/tests/test_crm_sales.py`, `test_crm_import.py` (16 test, OK) |
| Email | `apps/crm/services.py` `send_offer` + `apps/comms/mail.py`; `CRM_OFFER_SEND_EMAIL` default `0` |
| Migration review | `sqlmigrate` no-op choices; live data outcome uyğunluğu yoxlanıb |
| Docs | `CRM_FIELD_MAPPING.md`, `BUSINESS_DECISIONS.md` §A.10, `phase0-module-status.md` |

---

## Mərhələ B — Kommersiya nüvəsi (CRM → Lease → Space)

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| B1 | Huni UAT | Lead→Opp→Offer→LeaseApplication→draft Lease əl ilə keçir |
| B2 | Aktivləşmə | `SIGNED` + `start_date≤bugün` → `poll_lease_lifecycle --once` → ACTIVE + space/portal cascade |
| B3 | Bitmə xəbərdarlığı | ACTIVE + `end_date` pəncərədə → EXPIRING + in-app bildiriş |
| B4 | Occupancy SoT | Activate/terminate bridge; multi-line sync (M3) |
| B5 | Avtomatik test | `apps/leases/tests/test_lifecycle.py` yaşıl |
| B6 | Party cutover yox | Dual-write saxlanılır; Resident* SoT qalır |

### Sübut

| Sübut | Harada |
|-------|--------|
| Lifecycle | `apps/leases/services.py` `process_lease_lifecycle`; `poll_lease_lifecycle` |
| Poller flag | `bin/dev/entrypoint.py`, `bin/prod/entrypoint.py`, `.env.example` |
| Event | `LEASE_EXPIRING` — `apps/core/events.py` |
| SoT doc | `docs/architecture/party-space-lease-model.md` §7 |
| Test | `test_lifecycle` (activate + expiring) |

---

## Mərhələ C — Gündəlik bina əməliyyatları

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| C1 | Kart sifarişi | Portal: **Ad Soyad Ata adı** label/placeholder; ticket + employee yaranır |
| C2 | Reception | Check-in / check-out operator ssenarisi Pass |
| C3 | Security vs AxTrax | Günlük çıxış hesabatı oxu hadisələri ilə tutuşdurulur (yazma yox) |
| C4 | Ticket→WO | Minimum: ticket yarat → təyin → (istəyə bağlı) WO; boşluq statusda qeyd |
| C5 | Checklist | [functional-readiness-checklist.md](functional-readiness-checklist.md) §C doldurulub |

### Sübut

| Sübut | Harada |
|-------|--------|
| Kart adı | `apps/erp/forms.py` `PortalTicketForm.full_name`; `test_card_order` placeholder assert |
| Kart axını | `apps/residents/services.py` `create_employee_card_order`; portal `request_new` |
| Modul status | `phase0-module-status.md` — portal/reception/security/tickets **işlək** |
| Boşluqlar | `phase0-business-gaps.md` FLOW 2–4 |
| UAT §C | Checklist (operator imzası gözlənilir) |

---

## Mərhələ D — Billing düzgünlüyü

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| D1 | Journal gizlənməsi yox | `confirm_invoice` / `record_payment` uğursuz JE-də `DomainError` + rollback |
| D2 | Invoice kod race | Eyni transaksiyada unikal `INV-*`; `select_for_update` |
| D3 | Avtomatik test | `apps/billing/tests/test_services_hardening.py` yaşıl |
| D4 | Marketinq | “Tam mühasibat” deyilməz; CoA placeholder |
| D5 | Mühasib UAT | Trial balance açıqır; debitor tutuşdurması ayrıca (Pass/Defer) |

### Sübut

| Sübut | Harada |
|-------|--------|
| Kod | `apps/billing/services.py` — exception udulmur; `next_invoice_code` lock |
| Lease kod | `apps/leases/services.py` `next_lease_code` eyni pattern |
| Test | `test_services_hardening` + `apps/finance/tests/test_portal.py` |
| Status | billing/accounting **qismən** — `phase0-module-status.md` |

---

## Mərhələ M6 — Service Desk / Ticket

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M6-1 | Email outbox | `flush_email_outbox` / `poll_email_outbox` (TD-08) |
| M6-2 | Membership company notify | secondary membership alır |
| M6-3 | Portal delete scope | `company_ids` |
| M6-4 | Handoff doc = kod | tutan şöbə + Admin/Mgmt |
| M6-5 | C4 minimum | create→assign→WO; warehouse Phase 7–8 |

### Sübut

| Sübut | Harada |
|-------|--------|
| Doc | [m6-tickets-service-desk.md](../architecture/m6-tickets-service-desk.md) |
| Test | `apps/tickets/tests/test_m6_notify_outbox.py` |

---

## Mərhələ M5 — Portal / Reception / əməkdaşlar

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M5-1 | ID held → seriya | check-in / walk-in |
| M5-2 | Override path | `override_id` + səbəb; kuryer/list istisna |
| M5-3 | no_show RBAC | `cancel_visit` |
| M5-4 | Inactive host | pre_register rədd |
| M5-5 | Employee deactivate | ERP Admin/Management |
| M5-6 | AxTrax name ambiguity | multi-match skip |

### Sübut

| Sübut | Harada |
|-------|--------|
| Doc | [m5-portal-reception-employees.md](../architecture/m5-portal-reception-employees.md) |
| Test | `apps/reception/tests.py`, `test_deactivate_employee`, axtrax name match |

---

## Mərhələ M4 — CRM / Satış hunisi

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M4-1 | Huni test | `test_crm_sales` + `test_crm_import` yaşıl |
| M4-2 | Duplicate form restore | pending lead session → form |
| M4-3 | Draft LeaseLine / bank notes | `create_lease_draft` |
| M4-4 | **Prod gate açıq** | CRM **qismən**; A7 / UAT §A Pass olmadan işlək deyil |

### Sübut

| Sübut | Harada |
|-------|--------|
| Doc | [m4-crm-funnel.md](../architecture/m4-crm-funnel.md), A.10 |
| Test | `apps/crm/tests/test_crm_sales.py` |

---

## Mərhələ M3 — Əmlak / sahə / Lease lifecycle

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M3-1 | Multi-space sync | Activate/terminate/expiring → primary + `LeaseLine` |
| M3-2 | Terminate bridge | `Space.resident` clear; occupancy vacant |
| M3-3 | Portal cascade | Son open lease → `portal_active=False` |
| M3-4 | Draft LeaseLine | `ensure_primary_lease_line` CRM + LeaseService |
| M3-5 | Expiring | Mövcud poller + notice on all spaces |
| M3-6 | Cutover yox | `Space.resident` qalır (TD-02); B6 |

### Sübut

| Sübut | Harada |
|-------|--------|
| Services | `apps/leases/services.py` |
| Draft | `lease_ops.create_draft`, CRM `create_lease_draft` |
| Doc | [m3-property-lease-lifecycle.md](../architecture/m3-property-lease-lifecycle.md) |
| Test | `apps/leases/tests/test_lifecycle.py` |

---

## Mərhələ M2 — İcazələr və rezident scope

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M2-1 | Obyekt scope helper | `apps/accounts/object_scope.py` — company ≡ Party körpü |
| M2-2 | Multi-company ticket | Attachment/delete membership scope |
| M2-3 | Lease RBAC | `lease.view` siyahı/detal; `lease.edit` mutate |
| M2-4 | ROLE_MATRIX | Sales / Accountant / Resident seed |
| M2-5 | A.8 | Management `announcement.publish` grant-only |
| M2-6 | Sənəd | [m2-permissions-resident-scope.md](../architecture/m2-permissions-resident-scope.md) |

### Sübut

| Sübut | Harada |
|-------|--------|
| Scope | `apps/accounts/object_scope.py` |
| Ticket | `apps/tickets/access.py` |
| Lease | `apps/erp/views.py` LeaseList/Detail |
| RBAC | `apps/rbac/services.py` |
| Test | `apps/accounts/tests/test_object_scope.py` |

---

## Mərhələ M1 — Party/Person ↔ Resident* (ERP Core)

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| M1-1 | Uyğunluq xəritəsi | [m1-party-resident-mapping.md](../architecture/m1-party-resident-mapping.md) §1 |
| M1-2 | Dublikat qaydası + hesabat | `report_party_duplicates`; merge avtomatik yox |
| M1-3 | Cutover yox | Dual-write; Resident* ops SoT; UAT B6 |
| M1-4 | Sahiblik təsdiqi | Mapping §4 + phase0-data-ownership |
| M1-5 | Tək Company→Party sync | `company_sync` → `PartyService.upsert_*` |
| M1-6 | Audit + event_key | `party.upserted` / `person.upserted`; `emit(event_key=)` dedupe |

### Sübut

| Sübut | Harada |
|-------|--------|
| Mapping | `docs/architecture/m1-party-resident-mapping.md` |
| Dedupe | `apps/parties/dedupe.py`, `report_party_duplicates` |
| Sync | `apps/residents/company_sync.py`, `apps/parties/services.py` |
| Event | `apps/core/events.py` |
| Test | `apps/parties/tests/test_dedupe.py`, `test_phase2_core` emit dedupe |

---

## Mərhələ E — Security / NetAdmin (təxirə)

### Qəbul meyarları

| # | Meyar | Pass şərti |
|---|--------|------------|
| E1 | TLS / reverse proxy | Prod compose + secure cookie |
| E2 | Volumes / backup | `private_media` + outbox persistent; restore sınağı |
| E3 | DB rolları | `cp_migrator` ayrı; web start-da migrate yox |
| E4 | Poller supervision | Healthcheck + ayrı service / restart |
| E5 | Portal çıxış | NetAdmin: LAN / VPN / public qərarı |

**İndi:** E mərhələsi icra olunmur; funksional UAT-dan sonra açılır.

### Sübut (hazırkı borc)

| Sübut | Harada |
|-------|--------|
| Gap inventory | [Phase1 security gaps](6ac90806-369b-4f31-87eb-e8d735433165) araşdırma |
| Prod compose | `bin/prod/docker-compose.yml` — TLS/volume/health yox |
| Checklist §E | Açıq qalır |

---

## Mərhələ bağlama qeydi (şablon)

Hər mərhələ bağlananda doldurun:

```text
Mərhələ: __
Tarix: __
Qəbul edən: __
Meyarlar: A1… / B1… (Pass siyahısı)
Sübut linkləri: commit / test çıxışı / ekran / sənəd
İmza / qeyd: __
```

## Əlaqə

- Modul statusu: [phase0-module-status.md](../architecture/phase0-module-status.md)
- Biznes boşluqları: [phase0-business-gaps.md](../architecture/phase0-business-gaps.md)
- Biznes qərarları CRM: [BUSINESS_DECISIONS.md](../architecture/BUSINESS_DECISIONS.md) §A.10
