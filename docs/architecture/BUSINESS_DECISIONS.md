# Biznes qərarları (cavablandırılmış)

Mənbə suallar: [`finish-requirements.md`](finish-requirements.md), [`PRODUCT_DELIVERY_ROADMAP.md`](PRODUCT_DELIVERY_ROADMAP.md).

Yalnız burada qeyd olunan cavablar kod/ops-da tətbiq olunur; digər suallar açıq qalır.

---

## A.1 — SLA + iş təqvimi / bayramlar

**Status:** cavablandı · tətbiq olunub (2026-11-11)

**Cavab**

| Prioritet | SLA (business hours) |
|-----------|----------------------|
| Yüksək (`high`) | 4 saat |
| Normal (`normal`) | 8 saat |
| Aşağı (`low`) | 24 saat |
| Kritik (`critical`) | 2 saat *(əlavə qayda: yüksəkdən təcili; ayrıca təyin olunmayıb)* |

- İş günü: **Bazar ertəsi – Şənbə**, **09:00–18:00**
- Qeyri-iş: **Bazar** + **Novruz (20–24 mart)** + digər sabit dövlət bayramları  
  (`apps/tickets/business_calendar.py` → `FIXED_HOLIDAYS`)

**Kod**

- `SlaPolicy.hours` seed/migration `0022_sla_policy_a1_hours`
- `apply_sla()` → `add_business_hours()` (divar saatı deyil, iş saatı)

**Qeyd:** Modeldə ayrı response/resolution yoxdur — verilən saatlar həll (resolution) SLA kimi istifadə olunur. Dini bayramlar (Qurban və s.) hələ dinamik siyahıda deyil.

---

## A.2 — Ticket taxonomy + WO-eligible

**Status:** cavablandı · tətbiq olunub (2026-11-11)

**Cavab**

| Tip | Görünən kateqoriyalar (slug) |
|-----|------------------------------|
| Hadisə (`incident`) | `technical`, `cleaning`, `security`, `parking`, `other` |
| Xidmət sorğusu (`service_request`) | `technical`, `security`, `cleaning`, `other` |
| Kommersiya (`commercial`) | `commercial-space`, `lease`, `billing`, `administration`, `other` |
| Şikayət (`complaint`) | bütün aktiv kateqoriyalar |
| Təklif (`suggestion`) | UI-dən silinib |

- Yalnız **kateqoriya** filtri — altkateqoriya seed strukturu dəyişməyib.
- Bütün `RoutingRule.wo_eligible = True` (WO avtomatik yaranmır; yaratma icazəsi açıqdır).
- `crm_eligible` mövcud qaydalarla saxlanılır.

**Kod:** `apps/tickets/taxonomy_map.py`, seed + migration `0023_wo_eligible_all`, portal/ERP form + JS.

---

## A.3 — Kart sifarişi owner + status keçidləri

**Status:** cavablandı · tətbiq olunub (2026-11-11)

**Cavab**

| Mövzu | Qərar |
|-------|--------|
| Giriş UX | Portal «Yeni əməkdaş» → ticket create (`?intent=card_order`); ayrıca create section yox |
| Prefill | Tip: `service_request`; Kateqoriya: `security`; Altkateqoriya: `card-order` |
| Sahə | 1 space → avtomatik; 2+ → seçim |
| Kart səviyyəsi | Yalnız `card-order` altkateqoriyasında |
| Status owner | Yalnız **Security** |
| Kart vermə | Yalnız **AxTrax**; ERP/Security-də `card_number` əl ilə yazılmır |

**Status keçidləri:** `submitted → under_review → prepared → issued | rejected` (+ `cancelled`).  
`approved` istifadə olunmur. `issued` Security seçimi və/və ya AxTrax sync `card_number` yazanda avtomatik.

**Kod:** portal ticket prefill + `create_employee_card_order(space=…)`; Security card-order status service/UI; AxTrax people sync → `issued`.

---

## A.8 — Elan siyasəti: görünürlük + Zoho + kim yaradır

**Status:** cavablandı · tətbiq olunub (2026-11-12)

**Cavab**

| Mövzu | Qərar |
|-------|--------|
| Görünürlük | Bina-ümumi **və** 1 şirkət **və** seçilmiş bir neçə şirkət (`companies` M2M) |
| Mail → elan | **Zoho Mail** (Outlook əvəzinə). `all residents` qrupuna gedən maillər → bina-elmi elan |
| Kim yaradır (indi) | Yalnız **Admin** |
| Kim yaradır (sonra) | RBAC `announcement.publish` ilə təyin olunmuş staff |

**Kod:** `Announcement.companies`; `can_publish_announcement`; ERP elan create; `poll_zoho_announcements`.

---

## A.9 — Ticket eskalasiya + email + gözləmə kodu (Phase 6)

**Status:** cavablandı · tətbiq olunub (2026-11-12)

**Cavab**

| Mövzu | Qərar |
|-------|--------|
| Eskalasiya | Risk (≤2 business hour) → level 1; breach → level 2. Bildiriş: şöbə + Admin/Management. Avtomatik handoff/prioritet yüksəltmə yox |
| Waiting | Pause zamanı eskalasiya dayanır |
| Email | Status / mesaj / şöbə / eskalasiya → in-app + `enqueue_email` outbox (staff və rezident) |
| WaitingReasonCode | UI-də məcburi dropdown; `other` üçün mətn məcburi |
| First-response SLA | Ayrı deyil — resolution kifayətdir (A.1) |
| OrgDepartment merge | İndi yox; TicketDepartment SoT qalır |

**Kod:** `escalation_level` / `poll_ticket_sla_escalations`; `resume_sla` business hours; WaitingReasonCode UI.

---

## A.4 — İcarə qaydaları: rent/SC, index, depozit, parkinq, fit-out

**Status:** cavablandı · CRM ilə uyğunlaşdırılıb (2026-11-12)

| Mövzu | Qərar |
|-------|--------|
| Rent (CRM ofis paketi) | Default **33 AZN/m²** ƏDV-siz; **+18% ƏDV**; paketə kommunal (internet xaric), təmizlik, təhlükəsizlik, reception, 7/24 daxil — SC ayrıca sətir **yox** (bundled) |
| Billing charge engine | Lease-də rate×m² + addon qalır; CRM offer snapshot 33 AZN bundled tarifdən başlayır |
| Indexasiya | Sabit düstur yox — əl ilə / Management təsdiqli endirim |
| Depozit | Müqavilə ilə (adətən **2 ay**); xitamda zərər yoxdursa tam qaytarma |
| Parkinq | İcarəyə **daxil deyil**; ödənişsiz; müqavilədə qeyd |
| Fit-out | Avtomatik rent-free yox — müraciət forması qeydi |

**Kod:** `apps/crm` offer snapshot; `apps/leases` charge engine.

---

## A.10 — CRM / Satış əhatəsi

**Status:** cavablandı · V2 blank (2026-11-17) · owner: Satış/CRM

**Production gate:** Cari branch-dəki CRM dəyişiklikləri (V2 migration, UI, import, PDF) **qəbul olunana qədər production-hazır sayılmır.** Deploy yalnız Satış/CRM yazılı qəbulu + UAT §A Pass-dan sonra. Status cədvəli: `phase0-module-status.md`.

| Mövzu | Qərar |
|-------|--------|
| Modul | Bir ERP bloku CRM/Satış; Reception CRM yox |
| Rol | `sales` (mutate); Management (offer approve + RO); Accountant (LeaseApplication→Lease); **Admin CRM görmür** (texniki dəstək role-switch) |
| Huni | Lid → Qualification → İmkan → Təklif → Management → Müraciət formu → Mühasib → Lease/Documents |
| UI | Kanban yox — mərhələ zolağı + cədvəl; AZ dil |
| Qualification | `unreviewed` / `potential` / `non_potential` (+ səbəb) |
| Pipeline stage | Excel map: working…won/lost/on_hold (canonical kodlar) |
| Offer | Versiyalı; default 33 AZN/m² bundled +18% ƏDV; bütün göndərişlər Management təsdiqi; müddətsiz; PDF; 3 gün follow-up |
| Lease | Satış yaratmır — `LeaseApplication` → **mühasib** (hüquqşünas Phase 2); SoT Documents/Lease + CRM link |
| Party | Prospect təklif/imkan zamanı; resident/portal aktiv yalnız imzalı lease-dən sonra |
| Multi-space | Ayrı Offer + ayrı LeaseApplication + ayrı Lease |
| Reminder | Lid 24 iş saatı; Offer sent+3; lid mail bildirişi yox; idempotent |
| Hesabat | Ayrı CRM (mənbə/kvalifikasiya) və Satış (imkan/təklif/imza) tabları; snapshot/backup Phase 2 |
| Scope xaric | Meeting Room, website intake, reklam, commercial ticket→daxili lid, hüquqşünas rolu → Phase 2 |

**Kod:** `apps/crm`; ERP CRM views; `ApprovalService` `crm.offer.send`. Mapping: `docs/architecture/CRM_FIELD_MAPPING.md`.  
**M4 (2026-11-17):** hunisi möhkəmləndirmə (pending lead restore, activity, LeaseLine, PDF email attach) — [m4-crm-funnel.md](m4-crm-funnel.md). **Gate hələ açıq.**

### A.10 Phase 2 backlog (CRM)

| Maddə | Qeyd |
|-------|------|
| Meeting Room | Saatlıq icarə — ofis hunisindən ayrı |
| Bina reklam panelləri | Kommersiya inventar |
| Website lid | Form → `website_pending` → sales təsdiqi |
| Commercial ticket → daxili müştəri lid | Tickets bridge |
| Günlük report snapshot + DB backup | Ops job; CRM UI-dan ayrı |
| Hüquqşünas rolu | Mühasibdən ayrı lazım olarsa |
| Offer PDF corporate şablon upload | Default AZ generator Phase 1-də qalır |

---

## A.5 — Billing: invoice günü, due, VAT, cərimə

**Status:** cavablandı · tətbiq olunur (2026-11-12)

| Qayda | Qərar |
|-------|--------|
| Invoice pəncərəsi | Ayın **1–5**-i; draft → mühasib təsdiqi → ISSUED (gələcək: vergi inteqrasiyası) |
| Due | Normalda **1 ay** (issue + 30 gün) |
| Yeni kiracı | Müqavilə günündən **prorrata** (məs. ayın 15-i → yarım ay) |
| VAT | Qiymətlər ƏDV-siz; fakturada net + ƏDV 18% + gross |
| Cərimə | Müqaviləyə görə **mühasib əl ilə** (avto faiz düsturu yox) |

**Kod:** `apps/billing/policy.py`; finance portal AR.

---

## A.6 — CoA + jurnal kim yazır

**Status:** cavablandı · tətbiq olunur (2026-11-12)

| Mövzu | Qərar |
|-------|--------|
| CoA | **3-rəqəm** beynəlxalq plan — sistemə import; debitor/kreditor təsnifatı |
| Kassa / bank | Nəğd kassa (yalnız cash) + bank hesabları |
| Invoice/Payment → JE | Draft (unposted); **baş kitaba mühasib post edir** |
| Jurnal bağlama | Mühasib |
| Period close | Mühasib; bağlı dövrdə yeni JE yox |

**Kod:** `apps/accounting`; `/finance/` CoA import + post.

---

## A.7 — Approval matrix (ödəniş / maliyyə / CRM offer)

**Status:** cavablandı · tətbiq olunur (2026-11-12)

| Mövzu | Qərar |
|-------|--------|
| Ödəniş / kreditor | Bütün ödəniş əməliyyatları → **Management** təsdiqi |
| Finance portal | Yalnız **Accountant** (Admin/Management görmür) |
| Mutate (charge/invoice/JE) | Accountant; Management ödəniş təsdiqi ERP-də |
| CRM offer göndərişi | **Bütün** təkliflər (endirimli və ya yox) → Management `crm.offer.send` |
| CRM mutate | Yalnız **Sales**; Management lid/təklif redaktə etmir — yalnız approve/reject + RO |
| Avadanlıq / inventar | Baxış: FM, desk, management, admin, accountant; **mutate yalnız Accountant** |

**Kod:** `FINANCE_PORTAL_ROLES`; `ApprovalService` `finance.payment` / `crm.offer.send`; `can_mutate_building_assets`; ERP `approvals` / `payment_approvals`.

---

## Rəhbərlik (ERP daxilində)

**Status:** tətbiq olunur (2026-11-13)

Ayrı `/management/` shell yoxdur — rəhbər **ERP** istifadə edir. Login → `/erp/`. Köhnə `/management/*` bookmark-ları ERP-yə redirect olunur.

| Funksiya | Harada |
|----------|--------|
| Təsdiq növbəsi | `/erp/approvals/` |
| Ödəniş təsdiqi | `/erp/payment-approvals/` |
| CRM | Management RO + offer approve; Sales mutate; Admin CRM yox |
| Avadanlıq/inventar | ERP RO; mutate yalnız accountant |
| SLA / Aging / Dövrlər | ERP nav |

Demo: `manager@citypoint.az` / `manager123`.

---

## Finance portal (mühasib)

**Status:** A.4–A.7 uyğunlaşdırılır (2026-11-12)

Ayrı portal `/finance/` — Security kimi. Rol: yalnız `accountant`. **Admin/Management girmir** (ödəniş təsdiqi ERP-də). Avadanlıq/inventar `/finance/building-equipment/` və `/finance/building-inventory/` — **eyni Maliyyə shell** (navbar/brand dəyişmir); ERP URL-ləri digər rollar üçündür, mühasib ERP asset URL-indən finance-ə redirect olur. Demo: `accountant@citypoint.az` / `accountant123`.

---

## A.8 — AP / təchizatçı fakturası (mühəndis default + açıq Finance qərarları)

**Status:** qismən tətbiq · Finance təsdiqi gözlənilir (2026-11-23)

| Mövzu | Mühəndis default (kod) | Finance qərarı lazımdır |
|-------|------------------------|-------------------------|
| Orijinal faktura miqdarı | Saxlanılır (yenidən yazılmır) | — |
| order 10 / receive 6 / invoice 10 | Variance +4; bütün sənəd **HOLD**; AP JE **yox** | Over-receive qəbulu (HOLD-u qaldırıb tanıma) |
| MATCHED | Qəbul miqdarını **rezerv** edir | — |
| Void / cancel (matched) | Rezervi buraxır | — |
| Recognized | Unposted JE Dr expense / Cr AP (+VAT mapping) | GR inventar vs expense vaxtı; statutory VAT |
| Goods receipt | Bu gün **GL yazmır** (`POLine.received_qty` yalnız) | GR posting əlavə olunarsa tanıma ilə dublləşmə qadağası |
| Void (draft/hold/matched) | Rezerv buraxılır | — |
| Void (recognized, unposted JE) | Reverse draft JE + void + rezerv buraxılır | — |
| Void (recognized, **posted** JE) | **Bloklanır** — miqdar rezervdə qalır | Posted JE reverse / second-invoice release |
| AP ödəniş | `finance.supplier_payment` → Mgmt **approve** → mühasib **settle** (tarix+məbləğ+bank ref) → SPAY + unposted JE → `post_to_gl` | Bank sübutu; settle aktoru |
| Uğursuz/ləğv transfer | Mühasib `cancel_payment_authorization` (səbəb məcburi) → CANCELLED; rezerv buraxılır | Kim ləğv edir (Mgmt vs mühasib) — default mühasib |
| Bank reference | Global unique (case-insensitive) bir SPAY | Bir transfer → çox faktura? |

### Finance qərarları hələ açıq (operator qeydi)

1. **Qəbul / tanıma vaxtı (receipt timing):** GR inventar JE varmı, yoxsa yalnız AP tanıma (expense) — hazırkı default yalnız AP.
2. **AP ƏDV (VAT):** statutory dərəcə, input VAT hesabı və xərcə daxil/ayrı yazılış.
3. **Exception approval:** HOLD over-receive və ya qeyri-standart match üçün kim təsdiq edir.
4. **Posted JE reverse:** posted recognized fakturanın void/miqdar buraxılışı — bu gün **bloklanır**; reverse + ikinci faktura siyasəti təsdiq gözləyir.
5. **Partial / overpay:** kod partial 400+600 və over-allocation reject edir; exception overpay Finance təsdiqi ayrıca.
6. **Settlement sübutu:** mühəndis default — bank/transfer `reference` məcburidir; bank çıxarışı/PDF əlavəsi hələ yoxdur.
7. **Settlement icazəsi:** default mühasib (`can_mutate_finance`); ayrıca rol lazımdırmı?
8. **Unused approval ləğvi:** default mühasib + səbəb; rəhbərlik də ləğv etməlidir?
9. **Bir bank transfer → çox faktura:** hazırda qadağan (unique ref); allocation modeli lazımdırmı?

**Gözləmədə (provider):** bank feed, e-invoice adapter — provider sənədi + test mühiti olmadan həyata keçirilmir.

Kod: `apps/finance/ap_services.py`; `/finance/payables/`; ERP `/erp/payment-approvals/` (AP bölməsi). Sərhədlər: `docs/architecture/finance-integration-boundaries.md`.


