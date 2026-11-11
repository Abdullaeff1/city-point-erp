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
