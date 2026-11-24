# Finance integration boundaries — bank feed & e-invoice

**Tarix:** 2026-11-23

## Mövcud təkrar istifadə

| Element | Harada |
|---------|--------|
| Ödəniş metod / ref | `billing.Payment.method`, `reference` |
| JE mənbə açarları | `JournalEntry.source` + `source_ref` (idempotent) |
| CoA rolları | `accounting.coa.code_for` (`bank`, `cash`, `ar`, `ap`, `vat`) |
| Portal rəsmi faktura | `portal:invoice_official_download` |
| Təchizatçı xarici ref | `SupplierInvoice.external_ref` (boş; gələcək provider) |

## Goods receipt → GL

Hazırkı `procurement` qəbul axını **mühasibat yazılışı yaratmır** — yalnız `POLine.received_qty` yenilənir. AP tanıma bu checkout-da tək unposted JE yaradır (expense/AP). Finance sonradan GR inventar JE əlavə edərsə, eyni qəbul üçün ikinci tanıma qadağan edilməlidir.

## AP settlement (təchizatçı ödəniş)

| Addım | Kod / marşrut | Qeyd |
|-------|---------------|------|
| Ödəniş sorğusu | `request_supplier_payment` · `/finance/payables/<code>/` | Workflow `finance.supplier_payment` (AR-dan **ayrı**); PENDING+APPROVED unsettled məbləğ rezerv olunur |
| Təsdiq | `/erp/payment-approvals/` · `approve_supplier_pay` | **Yalnız** Authorization — SPAY yox, ops payable dəyişmir |
| Settlement | `record_supplier_payment` · `settle_pay` on payable detail | Sübut: `paid_at`, `amount`, `reference` (global unique) → SPAY + unposted JE; **ops düşür** |
| Ləğv (uğursuz transfer) | `cancel_payment_authorization` · səbəb məcburi | PENDING və ya APPROVED-unsettled → CANCELLED; rezerv buraxılır |
| Növbə | `/finance/payables/?queue=pending_approval\|awaiting_settle\|unposted_settle\|posted_settle` | Mühasib portal |
| GL post | `/finance/journals/<code>/` · `post_to_gl` | **Posted AP** yalnız JE postundan sonra; ops dəyişmir |

Posted AP faktura void: bloklanır — miqdar rezervdə qalır; Finance posted-JE reverse qərarı gözlənilir.

## Təklif olunan xarici müqavilə (provider-asılı deyil)

| Sahə | Məna |
|------|------|
| `external_id` | Bank/provider tranzaksiya və ya e-invoice ID |
| `provider` | `bank_feed` / e-invoice vendor kodu |
| `txn_date`, `amount`, `currency` | Tranzaksiya |
| `invoice_version` | E-invoice versiya |
| `submission_status` | prepared_internal → submitted_external → accepted_by_provider |
| `response_history` | JSON cavablar |
| `reconciliation_status` | unmatched / matched / disputed |
| `duplicate_key` | provider+external_id unique |

## Checkout-da həyata keçirilməyən

Canlı bank feed, e-invoice adapter, credentials saxlama, test sandbox — Finance provider seçimi + credentials prosesi + recon qaydaları təsdiqindən sonra.
