# Final System Acceptance — on-site UAT sheet

**Kandidat (dev):** `561ee9f` + working tree Phases 10–13 / FSA (commit edilməmiş dəyişikliklər daxil).  
**Lokal suite:** 791 OK (2026-11-23). Hesabat: [`final-system-acceptance-release-report.md`](final-system-acceptance-release-report.md).  
**Məqsəd:** İnkişaf sübutunu on-site imzaya çevirmək. Bu vərəq **boş nəticə** ilə başlayır — yerli test Pass ≠ operator/Finance/NetAdmin imzası.

**Qayda:** Hər sətir üçün: Pass / Fail / Blocked + imza + tarix. Defer yalnız biznes sahibi yazılı qərar verdikdə.

---

## A. Axın 1 — Yeni rezident (Sales → Mühasib → Rezident)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 1.1 | Sales | Boş lid | Lead→Opp→Offer→Management approve→send | Offer SENT | Offer kodu / PDF | | |
| 1.2 | Sales | SENT offer | LeaseApplication → mühasibə | SUBMITTED | App kodu | | |
| 1.3 | Mühasib | App | Accept → draft Lease → signed complete | Lease ACTIVE, space ACTIVE | Lease kodu | | |
| 1.4 | Rezident | Portal login | Şirkət seçimi, müqavilə/fakturaya baxış | Scope düzgün | Ekran | | |
| 1.5 | — | Website intake | Public API / website form | Mövcud / defer | Sahib: Sales/IT | | |

**Defer namizədi:** Website intake (əgər LAN website yoxdursa) — sahibi: Sales/IT.

---

## B. Axın 2 — Əməkdaş kart / AxTrax RO (Rezident → Security → NetAdmin)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 2.1 | Rezident | Portal | Kart sifarişi (Ad Soyad Ata adı + ID) | Ticket security queue | Ticket kodu | | |
| 2.2 | Security | Ticket | Review + tələb olunan səviyyə | Status irəliləyir | Ticket | | |
| 2.3 | NetAdmin | AxTrax | Kart fiziki emit (xaricdə) | Kart nömrəsi AxTrax-da | AxTrax id | | |
| 2.4 | System | Poller | RO sync | Employee + events ERP-də | Sync log | | |
| 2.5 | Security | Attendance | Deaktiv əməkdaş tarixçəsi | Keçmiş event qalır | Access view | | |

---

## C. Axın 3 — Qonaq (Reception + NetAdmin)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 3.1 | Rezident | Portal | Pre-register | Visit yaradılır | Visit kodu | | |
| 3.2 | Reception | Visit | Check-in ± guest card | IN status | Reception UI | | |
| 3.3 | Reception | Inside | Check-out / delayed OUT | OUT; kart reuse mümkün | Visit | | |
| 3.4 | NetAdmin | QONAQ | Membership + reader direction | Live təsdiq | NetAdmin note | | |

---

## D. Axın 4 — Texniki ticket (Desk → FM → Anbar → Rezident)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 4.1 | Rezident | Portal | Ticket yarat | Queue + SLA | Ticket | | |
| 4.2 | Service Desk | Ticket | Assign / handoff FM | WO yaradılır | WO kodu | | |
| 4.3 | FM / Texnik | WO | Material issue | StockMovement + qty | Movement | | |
| 4.4 | FM | WO | Complete | Rezident görünən closure | Portal/ticket | | |

---

## E. Axın 5 — Kommersiya sorğusu (Rezident → Desk → Sales)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 5.1 | Rezident | Portal | COMMERCIAL ticket | Ticket saxlanır | Ticket kodu | | |
| 5.2 | Sales | Ticket ref | Manual CRM lead/opp/offer | Ticket kodu lead note-da | Lead | | |
| 5.3 | Sales/Mühasib | Offer | Lease/amendment path | Yeni/yenilənmiş lease | Lease | | |

---

## F. Axın 6 — Satınalma (FM → Management → Anbar)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 6.1 | FM | Low stock / WO | PR yarat | PR pending | PR kodu | | |
| 6.2 | Management | PR | Approve → RFQ/PO | Priced commitment | PO | | |
| 6.3 | Anbar | PO | Partial receive | Stock artımı | Receipt | | |
| 6.4 | Finance | — | PO→supplier invoice→AP JE | **Açıq boşluq** | Sahib: Finance | | |

**Launch defer (şüurlu):** AP/payable subledger — owner: Finance. ERP PR→PO→stock işlək qalır.

---

## G. Axın 7 — Billing / collection (Mühasib → Management → Rezident)

| # | Operator | Başlanğıc | Əməliyyat | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|-----------|-----------|------------|-------|--------|------|
| 7.1 | Mühasib | Active lease | Charge → draft invoice → confirm | ISSUED + unposted JE | INV kodu | | |
| 7.2 | Mühasib | JE | Baş kitaba yaz | Posted | JE kodu | | |
| 7.3 | Mühasib/Mgmt | Payment 400+600 | Approve + record | Portal qalıq 600→0; GL post portalı yenidən azaltmır | Portal + JE | | |
| 7.4 | Mühasib | TB / Management | Trial balance + `/erp/reports/` | Rəqəmlər uzlaşır | Export | | |

---

## H. Finance qəbulu (statutory)

| # | Sahib | Maddə | Nəticə | İmza |
|---|-------|-------|--------|------|
| H1 | Finance | Real CoA Excel import | | |
| H2 | Finance | `ACCOUNTING_ROLE_CODES` / AR mapping | | |
| H3 | Finance | ƏDV / depozit öhdəlik | | |
| H4 | Finance | Opening balances | | |
| H5 | Finance | AP path (6.4) qəbul və ya defer | | |

---

## I. NetAdmin / infrastruktur

| # | Sahib | Maddə | Nəticə | İmza |
|---|-------|-------|--------|------|
| I1 | NetAdmin | TLS / reverse proxy | | |
| I2 | NetAdmin | AxTrax poller scheduled + health | | |
| I3 | NetAdmin | Offline LAN smoke (uplink unplug) | | |
| I4 | NetAdmin | Backup + disposable restore drill | | |
| I5 | NetAdmin | `cp_migrator` vs `cp_app` | | |

---

## J. Management reporting

| # | Sahib | Maddə | Nəticə | İmza |
|---|-------|-------|--------|------|
| J1 | Management | `/erp/reports/` as-of + Excel | | |
| J2 | Management | Snapshot vs reconstruction başa düşülür | | |
| J3 | Management | Rəsmi KPI siyahısı | | |
