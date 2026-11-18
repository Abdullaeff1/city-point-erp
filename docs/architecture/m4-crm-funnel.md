# M4 — CRM / Satış hunisi

**Status:** icra olunub · **production gate AÇIQ** (2026-11-17)  
**Qayda:** CRM **işlək / production-hazır sayılmır** — A.10 + UAT §A Pass + yazılı Satış qəbulu tələb olunur.

---

## 1. Huni

`Lead → Opportunity → Offer (+version/approval) → LeaseApplication → Lease draft`

ACL: Sales mutate; Management approve/RO; Accountant LeaseApplication; **Admin CRM görmür**.

---

## 2. M4 düzəlişləri (gate bağlanmayıb)

| Maddə | Nəticə |
|-------|--------|
| Duplicate lid form | `crm_pending_lead` session → form restore + force_create checked |
| Lead status activity | `update_lead` → `LeadActivity` STATUS_CHANGE |
| LeaseLine on drafts | `create_lease_draft` + deprecated `convert_offer_to_lease_draft` |
| Bank/VÖEN snapshot | LeaseApplication → lease.notes |
| Offer email | `CRM_OFFER_SEND_EMAIL=1` → PDF attach (`send_templated_email`) |
| Stale Admin comments | mixin / nav comments A.10 uyğun |

---

## 3. Qəbul (M4 texniki) vs prod gate

| # | Meyar | Pass |
|---|--------|------|
| M4-1 | Huni kod yolu yaşıl | test_crm_sales / import |
| M4-2 | Pending lead restore | UI + test |
| M4-3 | Draft LeaseLine | test |
| M4-4 | Gate açıq | modul **qismən**; checklist §A unchecked |

**A7 / prod:** yalnız Satış yazılı qəbul + UAT §A bütün sətirlər Pass.  
Forma: [../uat/crm-written-acceptance.md](../uat/crm-written-acceptance.md) (`AWAITING_SIGNATURE`).
