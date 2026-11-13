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

**Status:** cavablandı · tətbiq olunur (2026-11-12) · owner: Satış/CRM

| Mövzu | Qərar |
|-------|--------|
| Modul | Bir ERP bloku CRM/Satış; Reception CRM yox |
| Rol | `sales` (mutate); Management (offer approval); Accountant (LeaseApplication→Lease); Admin read-only |
| Huni | Lid → Qualification → İmkan → Təklif → Management → Müraciət formu → Mühasib → Lease/Documents |
| Qualification | `unreviewed` / `potential` / `non_potential` (+ səbəb) |
| Pipeline stage | Excel map: working…won/lost/on_hold (canonical kodlar) |
| Offer | Versiyalı; default 33 AZN/m²; bütün göndərişlər Management təsdiqi; müddətsiz; 3 gün follow-up |
| Lease | Satış yaratmır — `LeaseApplication` → mühasib; Party imzadan sonra |
| Multi-space | Ayrı Offer + ayrı LeaseApplication + ayrı Lease |
| Reminder | Lid 1 calendar day; Offer sent+3; idempotent |
| Scope xaric | Meeting Room, website intake, reklam, Excel tarixi import → Phase 2 |

**Kod:** `apps/crm`; ERP CRM views; `ApprovalService` `crm.offer.send`. Mapping: `docs/architecture/CRM_FIELD_MAPPING.md`.

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
| Finance portal | Yalnız **Accountant + Management** (Admin görmür) |
| Mutate (charge/invoice/JE) | Accountant; Management = baxış + ödəniş təsdiqi |
| CRM offer göndərişi | **Bütün** təkliflər (endirimli və ya yox) → Management `crm.offer.send` |

**Kod:** `FINANCE_PORTAL_ROLES`; `ApprovalService` `finance.payment` / `crm.offer.send`.

---

## Finance portal (mühasib)

**Status:** A.4–A.7 uyğunlaşdırılır (2026-11-12)

Ayrı portal `/finance/` — Security kimi. Rol: `accountant` (+ `management` baxış/təsdiq). **Admin birbaşa görmür** (role-switch preview istisna). Demo: `accountant@citypoint.az` / `accountant123`.
