# Satınalma — sətir səviyyəsi RFQ sourcing (qəbul hesabatı)

**Tarix:** 2026-11-23  
**Git baza:** `561ee9f0ff11cccd750223cc6894899c145ef687`  
**Migrasiya:** `procurement.0006_line_level_sourcing`  
**Fokus suite:** `apps.procurement.tests.test_line_level_sourcing` → **9 OK**  
**Procurement suite:** `apps.procurement` → **56 OK**  
**Tam suite:** `manage.py test --keepdb` → **809 OK** (0 fail / 0 skip)

---

## 1. İşlənmiş 10 sətir ssenarisi

| Addım | Nəticə |
|-------|--------|
| PR 10 sətir (hər biri qty 10) → təsdiq → RFQ | OK |
| A: bütün 10 sətir; B: 1–4; C: 5–10 | Dəvət əhatəsi + `request_text` saxlanılır |
| Dispatch yalnız sübutla (`dispatch_ref` / email|manual|outbox + mark) | Draft təkbaşına `dispatched_at` yazmır |
| Dəvət amendment | Yeni invitation `supersedes` ilə; köhnə sübut silinmir |
| Coverage: `NOT_INVITED` / `INVITED_UNANSWERED` / `QUOTED` (o cümlədən unit_price=0) | Müqayisə matrisində görünür |
| Əhatədən kənar quote sətri | `DomainError` |
| Qismən qty təklif | Görünür, bütöv sətir mükafatı **bloklanır** |
| B və C fərqli sətirləri qazanır → ayrı PO | Hər `POLine` → `pr_line` + `quote_line` |
| C maliyyə təsdiqi gözləyərkən B issued | Retry B-ni təkrarlamır; C təsdiqdən sonra issued |
| Quote dəyişikliyi (stale fingerprint) | Köhnə commitment ilə PO **yox** |
| Sətir bölünməsi (`qty` ≠ qalan) | City Point gözlənilir — `DomainError` |
| Legacy header quote | Aktiv mükafat yoxdursa işləyir; mükafat varsa bloklanır |
| Qismən qəbul | `received_qty` + PR progress izlənir |

---

## 2. Marşrutlar və icazələr

| UI / əməliyyat | Yol | İcazə |
|----------------|-----|--------|
| RFQ detail | `/erp/procurement/rfq/<code>/` | `procurement.view` |
| Dəvət / sətir təklifi / mükafat / multi-PO | eyni (POST) | `procurement.edit` |
| Management öhdəlik təsdiqi | `/erp/approvals/` (`procurement.commitment`) | Management |
| Proses PR təsdiqi | mövcud PR axını | `procurement.approve` / Admin |

Operator rolları dəyişməyib: Facility procurement edit; Management maliyyə öhdəliyi.

---

## 3. Model / migrasiya

Yeni / genişləndirilmiş:

- `RFQInvitation`, `RFQInvitationLine` (əhatə + dispatch sübutu + `supersedes`)
- `RFQQuote.invitation`, `supplier_reference`, `valid_until`
- `RFQQuoteLine` (`quoted` \| `unanswered`, VAT sahələri)
- `PRLineAward` (bir aktiv mükafat / PR sətri; `po_line` bağlanması)
- `POLine.pr_line`, `POLine.quote_line`

Servis: `apps/procurement/line_sourcing.py` → `ProcurementService` fasadləri.

---

## 4. Test nəticələri

```text
# Fokus
python manage.py test apps.procurement.tests.test_line_level_sourcing --keepdb
→ 9 OK

# Procurement
python manage.py test apps.procurement --keepdb
→ 56 OK

# Tam suite
python manage.py test --keepdb
→ 809 OK
```

---

## 5. City Point-də qalan qərarlar

1. **Sətir bölünməsi** — bir PR sətrinin bir neçə təchizatçıya qty bölünməsi hələ **bloklanır**; biznes təsdiqi gözlənilir.
2. **Vergi / xərcləmə bazası** — `PROCUREMENT_QUOTE_VAT_RATE=0.18` yalnız test/sintetikdir. Canlı authorization Finance-təsdiqli net/gross/ƏDV qaydasına bağlanmalıdır; naməlum baza → UI «vergi bazası naməlum» + Management escalation.
3. **Növbəti mərhələ** — təchizatçı hesab-faktura / AP matching (bu çatdırılmanın əhatəsindən kənar).

---

## 6. Operator qısa yol

1. PR təsdiq → RFQ yarat  
2. Təchizatçı dəvəti (sətir checkbox + istəyə görə dispatch ref)  
3. Sətir təklifi (0 = quoted; cavabsız = unanswered)  
4. Müqayisə matrisindən bütöv sətir mükafatı  
5. «Mükafatlardan PO yarat» → bannerlər: `issued` / `awaiting_financial_approval` / `failed`  
6. Gözləyən təchizatçı üçün Approvals-da commitment → yenidən PO

---

*AP / invoice matching növbəti milestone.*
