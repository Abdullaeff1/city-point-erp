# CRM / Satış — yazılı qəbul (A7)

**Məqsəd:** M4 production gate-i bağlamaq.  
**Qayda:** Bu forma **imzalanmadan** CRM «production-hazır» və ya marketinq «hazır» sayıla bilməz.  
**İstinad:** [phase-acceptance-criteria.md](phase-acceptance-criteria.md) §A · [functional-readiness-checklist.md](functional-readiness-checklist.md) §A · [../architecture/BUSINESS_DECISIONS.md](../architecture/BUSINESS_DECISIONS.md) §A.10

---

## 1. Kod hazırlığı (engineering — artıq)

| Sübut | Status |
|-------|--------|
| `apps/crm/tests/test_crm_sales.py` + `test_crm_import.py` | Yaşıl (lokal) |
| Offer Management approval + PDF | Kodda |
| LeaseApplication → draft Lease | Kodda |
| CRM/Satış hesabat tabları | Kodda |
| Modul statusu «qismən / prod gate» | [phase0-module-status.md](../architecture/phase0-module-status.md) |

---

## 2. Operator UAT §A (Satış / Management keçirir)

Mühit: _______________ (dev / staging) · Tarix: _______________

| # | Ssenari | Pass / Fail / Blocked | Qeyd |
|---|---------|----------------------|------|
| A1 | Lead → Opportunity → Offer version | | |
| A2 | Management approval olmadan send mümkün deyil | | |
| A3 | Offer PDF; send → SENT (`CRM_OFFER_SEND_EMAIL` yalnız açıqdırsa mail) | | |
| A4 | LeaseApplication → draft Lease (bank / form sahələri) | | |
| A5 | CRM vs Satış hesabat səhifələri açılır | | |
| A6 | `import_crm_leads_xlsx` nümunə faylda dry-run + `--apply` | | |

**§A nəticə:** bütün sətirlər Pass olmalıdır. Fail/Blocked varsa gate açıq qalır.

---

## 3. Yazılı qəbul

| Sahə | Dəyər |
|------|-------|
| Təşkilat | City Point |
| Modul | ERP CRM / Satış (V2 blank + hunisi) |
| Qəbul edən (ad, vəzifə) | |
| Tarix | |
| Mühit (staging URL / host) | |

**Bəyanat (imza üçün):**

> Yuxarıdakı UAT §A ssenarilərini keçirdim. CRM/Satış modulunu **pilot/production istifadəsinə** qəbul edirəm. Bilirəm ki: Meeting Room, website lid, AxTrax write və Party cutover bu qəbulun xaricindədir (Phase 2 / ayrıca).

İmza: ______________________ · Tarix: __________

---

## 4. Gate bağlandıqdan sonra

1. [functional-readiness-checklist.md](functional-readiness-checklist.md) §A checkbox-ları Pass edin.
2. [phase0-module-status.md](../architecture/phase0-module-status.md) — CRM sətirini «işlək (UAT Pass)» yeniləyin; prod gate qeydini bağlayın.
3. [phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md) — M4 / P0 #1 yeniləyin.
4. Deploy yalnız `SEED_DEMO=0` + staging/prod `.env` ilə.

**Cari status:** `AWAITING_SIGNATURE` (2026-11-18)
