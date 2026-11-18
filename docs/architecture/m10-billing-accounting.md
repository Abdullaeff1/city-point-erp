# M10 — Billing və Accounting

**Status:** icra olunub (2026-11-18)  
**Defer:** real City Point CoA Excel (müştəri faylı); trial balance ↔ xarici mühasibat UAT; PO↔invoice UI e2e

---

## 1. Billing (A.5)

| Maddə | Kod |
|-------|-----|
| Pəncərə / due / VAT 18% | `billing.policy` |
| Lease charge (prorrata, təkrarsız) | `generate_monthly_lease_charges` |
| Charge → draft invoice | `generate_invoice_from_charges` |
| Draft → ISSUED + JE | `confirm_invoice` |
| Qismən/tam ödəniş + Party | `record_payment` (`Payment.party`) |
| Ləğv | `void_invoice` (+ JE reverse) |
| Cərimə | `apply_penalty_charge` (əl ilə) |
| Portal borc | `portal:invoices` |

---

## 2. Accounting (A.6)

| Maddə | Kod |
|-------|-----|
| Placeholder 3-digit CoA + xlsx import | `accounting.coa` / `import_coa_from_xlsx` |
| Idempotent JE | `JournalEntry.source_ref` (`invoice:N` / `payment:N`) |
| Revenue split | charge source → rent/SC/penalty/other CoA roles |
| JE code race | `_next_je_code` + `select_for_update` |
| Aktiv hesab + açıq dövr | `post_journal` |
| Post / reverse | `post_to_gl` / `reverse_journal` |
| Period close/reopen + audit | `close_period` / `reopen_period` |
| Trial balance / AR aging | finance portal |

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M10-1 | JE fail → invoice/payment rollback | mövcud test |
| M10-2 | Idempotent invoice/payment JE | test |
| M10-3 | Partial→full payment + party | test |
| M10-4 | Void + reverse | test |
| M10-5 | Inactive account blocked | test |
| M10-6 | Portal invoices scope | test |

UAT tracker: [../uat/coa-import-uat.md](../uat/coa-import-uat.md) — real CoA import + TB tutuşdurma (mühasib doldurur).
