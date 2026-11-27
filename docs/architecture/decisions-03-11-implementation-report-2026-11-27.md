# City Point — Qərarlar 03 / 04 / 05 / 07 / 08 / 11 — icra hesabatı

**Tarix:** 2026-11-27  
**Mühit:** lokal Docker + PostgreSQL test DB (sintetik data)  
**Qadağalar saxlanılıb:** deploy / canlı data silmə / vendor / xarici ödəniş / CoA ixtirası yox

---

## Qısa verdiktlər

| Qərar | Verdikt | Qısa |
|-------|---------|------|
| **D07** | **PASS** | Üç ayrı case; ID-held 24s → Reception+Security; komanda + replay testləri |
| **D03** | **PASS** | 10=6+4 award/PO/receipt; free=requested−ordered−unissued; concurrency |
| **D08** | **COMPLETE** (rollout əhatəsi) | Ticket + CRM təklif PDF + Finance/Portal → kanonik Document; digər siloslar aşağıda |
| **D05** | **PASS** | Versiya paylaşımı; sübut≠ödəniş; 1000→600 bir dəfə; Finance növbə |
| **D04** | **PASS** | AP Mgmt təsdiqi (istisna yox) ≠ settlement; AR Finance verification; RO cəmlər |
| **D11** | **PASS (hazırlıq)** | Lokal checklist yazıldı; prod təmizlik ayrıca qərardır |

---

## D07 — Qonaq overdue

**Marşrutlar / aktorlar**
1. Cardless INSIDE → portal şirkət üzvləri (`visitor.checkout_overdue…`) → `/portal/guests/?overdue=1`
2. INSIDE + ID held + 24s → Reception + Security (`visitor.id_held_overdue…`) → `?status=inside_overdue`
3. RETURN_PENDING → mövcud event → `?status=id_pending` (inside overdue deyil)

**Poller:** `manage.py poll_guest_checkout_overdue` → `process_guest_overdue_alerts()`  
**Test:** `apps.reception.tests_guest_checkout_ownership` — **14 OK**  
**Ops:** [docs/uat/guest-checkout-overdue-ops.md](../uat/guest-checkout-overdue-ops.md)

---

## D03 — PR sətirinin bölünməsi (10 filter)

**Nümunə (DB):** requested 10 → award A=6, B=4 → free 0, ordered 0, allocated 10 → Mgmt yalnız A → issue A: ordered 6, allocated 4 → issue B: ordered 10 → receive A 2+4, B 4 → received 10, outstanding 0. Replay eyni `operation_key` stock artırmır.

**Marşrut:** `/erp/procurement/rfqs/<code>/` — Supply mükafat miqdarları → Management commitment → PO  
**Miqasiya:** `procurement.0007_pr_line_award_split`  
**Test:** `apps.procurement.tests.test_line_level_sourcing` — **10 OK**

---

## D08 — Mərkəzi arxiv (tamamlama 2026-11-27)

**Management:** `/erp/documents/` (yalnız MANAGEMENT/ADMIN) + filtrlər (şirkət, mənbə, tip, tarix, əlaqəli kod / təklif №, yükləyən, görünmə); IN/OUT → `/erp/correspondence/`  
**Kanonik upload:** Finance + Portal sübut + **Ticket əlavələri** + **CRM təklif PDF** → `Document`/`DocumentVersion`  
**Miqasiya:** `documents.0009_d08_ticket_crm_archive` (`Document.offer`), `tickets.0026_d08_ticket_crm_archive` (`TicketAttachment.document` / `visible_to_resident` / `uploaded_by`)  
**Inventar / backfill (lokal):**  
- `manage.py inventory_document_uploads --dry-run`  
- `manage.py backfill_document_archive` (dry-run) / `--apply` (idempotent; mənbə fayl silinmir; **prod tətbiq yox**)  
**Test (bu dəyişiklik):**  
`apps.documents.tests.test_decision08_ticket_crm_archive` + `test_decision08_archive` + `test_decision05_payment_evidence` + attachment/card-order slice → **44 OK**

### Operator nümunəsi — Ticket
1. Rezident A portalda sorğuya PDF yükləyir → `TicketAttachment(visible_to_resident=True)` + `Document(ticket=…, PUBLIC_RESIDENT)`.  
2. Service Desk eyni ticketə daxili fayl yükləyir → `visible_to_resident=False` + `INTERNAL`.  
3. Management `/erp/documents/?source=ticket&related=<TK-kod>&company=A` — hər iki sənədi görür.  
4. Rezident A yalnız portal-görünən faylı endirir; daxili 404. Şirkət B / kopyalanmış URL — 404. Şirkət konteksti dəyişəndə ACL yenidən qiymətləndirilir.

### Operator nümunəsi — CRM
1. Sales təklif v1 PDF yaradır → `OfferVersion.pdf_file` + eyni `Document(offer=…)` v1.  
2. Paylaşım / göndərmə → `portal_shared_version=v1`.  
3. Sales v2 qaralama PDF → arxivə v2 əlavə olunur; portal hələ v1 qaytarır.  
4. Management `source=crm` + təklif № ilə tapır.

### Arxiv əhatəsi (modul)

| Modul | Owner | Storage | Kanonik Document? | Status |
|-------|-------|---------|-------------------|--------|
| Finance invoice / sübut | Accountant | private Document | Bəli | **Integrated** |
| Portal resident docs | Portal | Document | Bəli (oxu/paylaşım) | **Integrated** |
| ERP resident vault | Admin/Mgmt | Document | Bəli | **Integrated** |
| Kargüzarlıq IN/OUT | document.edit | Document + registry № | Bəli (məktub) | **Integrated** |
| TicketAttachment | Service Desk / Portal | dual-write + Document | Bəli | **Integrated** |
| CRM Offer PDF | Sales | dual-write `crm/offers/` + Document | Bəli | **Integrated** |
| LeaseApplication real sənədlər | Sales/Accountant | Document (vault) | Bəli | **Integrated** (checklist JSON fayl deyil) |
| Work Order biznes faylı | FM | Document FK var; WO FileField yox | N/A | **Out of first-rollout upload surface** |
| Procurement UI attach | Supply | Document FK; UI upload zəif | Partial | **PENDING UI** — Supply |
| Announcement / BuildingProcedure | Comms | ayrı private store | Xeyr | **Ayrı məhsul səthi** — Comms |
| BuildingAsset.document | Property | MEDIA | Xeyr | **Texniki pasport** — Property |
| ResidentEmployee.id_document | Residents | `employees/id/` | Ticketə nüsxə kanonik | ID əsli ayrıca (kart sifarişi ticket arxivə yazılır) |
| Space drawings / plans | Property/Security | plan storage | Xeyr | **Texniki** — arxivə köçürmə yox |

**Verdikt:** Birinci rollout biznes sənəd yolları (Ticket, CRM təklif, Finance/Portal, vault, kargüzarlıq) kanonik arxivdədir → **D08 COMPLETE** bu əhatə üçün. Procurement UI attach və Comms/Property silosları ayrı sahiblə qalır; canlı prod backfill icra edilməyib.

---

## D05 — Mühasib ↔ rezident maliyyə sənədləri

**Addımlar**
1. Accountant: faktura səhifəsindən rəsmi PDF → `upload_official_invoice_document`
2. Explicit share versiya → portal `portal_shared_version` (v1 share → v2 draft → v1 qalır → share v2)
3. Resident: ödəniş tapşırığı yükləyir → `InvoicePaymentEvidence` (balance dəyişmir)
4. Finance: `/finance/payment-evidence/` → yoxlama / `record_incoming_payment_verified` → balance bir dəfə

**Nümunə:** AZN 1000 → sübut 400 → balanse **1000** → verified payment → **600** (bir Payment, bir JE mənbəyi)  
**Miqasiya:** `billing.0008_invoice_payment_evidence`, `documents.0008_portal_shared_version`  
**Test:** `apps.billing.tests.test_decision05_payment_evidence` (+ archive) — **26 OK**

---

## D04 — İstiqamət üzrə səlahiyyət

**AP (çıxış):** hər məbləğ (AZN 1 daxil) əvvəlcə Management; təsdiq ≠ settlement ≠ JE post; ekranda alıcı, məqsəd, PO/PR, öhdəlik, rezerv, qalan.  
**AR (giriş):** `record_incoming_payment_verified` — Mühasib; köhnə PENDING `finance.payment` eyni məbləğ üçün CANCEL (double-post yox).  
**RO cəmlər:** ödəniş təsdiqləri səhifəsində AR/AP pending/settled + sübut sayğacı.  
**Test:** `apps.finance.tests.test_decision04_payment_authority` + mövcud AP 1000/400/600 — **3 OK** (bu qaçış)

---

## D11 — Rollout hazırlığı

Checklist: [docs/uat/decision11-initial-rollout-checklist.md](../uat/decision11-initial-rollout-checklist.md)  
Prod data seçimi/təmizlik — **City Point ayrıca qərarı**; bu icrada edilməyib.

---

## Test sayları (hədəflənmiş)

| Suite | Nəticə |
|-------|--------|
| reception `tests_guest_checkout_ownership` | 14 OK |
| procurement `test_line_level_sourcing` | 10 OK |
| documents archive + billing evidence | 26 OK |
| finance decision04 + AP recon slice | 3 OK |
| **Cəmi qərar suite-ləri (əvvəl)** | **53 OK** |
| Merge follow-up (line_level + phase9 + workflow_e + phase6 + D08/D05/D04) | **60 OK** |
| D08 ticket/CRM archive + D05/D08 regression + attachment/card-order | **44 OK** |

```text
docker compose exec -T web python manage.py test \
  apps.documents.tests.test_decision08_ticket_crm_archive \
  apps.documents.tests.test_decision08_archive \
  apps.billing.tests.test_decision05_payment_evidence \
  apps.tickets.tests.test_department_access.TicketDepartmentAccessTests.test_attachment_staff_and_resident \
  apps.residents.tests.test_card_order \
  --keepdb
```

Tam ERP suite qaçırılmayıb (tələb üzrə).

---

## Qalan açıq (sahib)

| Maddə | Owner |
|-------|-------|
| Real CoA / statutory ƏDV | Finance |
| AxTrax LAN + TLS + backup | NetAdmin |
| Retention müddətləri | Hüquq / Management |
| Ticket/CRM historical `--apply` (prod) | Dev + Ops (ayrı qərar; lokal dry-run var) |
| Procurement UI → Document upload | Supply |
| Comms announcement/procedure → arxiv? | Comms / Management qərarı |
| Operator on-site imza | Ops |
| Prod resident seçimi / wipe | Management |

Təsdiqlənmiş biznes qaydaları (03–05, 07–08, 11) yenidən açılmır.
