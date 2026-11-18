# Real CoA + Trial Balance UAT (M10)

**Məqsəd:** Placeholder 3-digit CoA-nı müştəri planı ilə əvəz etmək və mühasib TB tutuşdurması.  
**Qayda:** Bu UAT Pass olmadan billing «statutory kitab» kimi imzalanmır. ERP daxili JE/TB işləyə bilər.  
**İstinad:** [../architecture/m10-billing-accounting.md](../architecture/m10-billing-accounting.md) · [functional-readiness-checklist.md](functional-readiness-checklist.md) §D · A.6 [../architecture/finish-requirements.md](../architecture/finish-requirements.md)

**Cari status:** `AWAITING_CLIENT_COA` (2026-11-18) — seed = placeholder `100`/`101`/`110`/…

---

## 1. Kod hazırlığı (engineering)

| Element | Harada |
|---------|--------|
| Placeholder CoA | `apps/accounting/coa.py` (`DEFAULT_COA_ROWS`) |
| Import | `import_coa_from_xlsx` / Finance UI upload |
| Role → kod | `code_for("ar"|"rent_revenue"|…)` — real kodlar import + mapping ilə uyğunlaşdırılmalıdır |
| TB | Accountant trial balance view |
| Testlər | `apps/billing/tests/test_m10_billing.py` (placeholder) |

---

## 2. Excel formatı (müştəri təqdim edir)

Sütunlar (1-ci sətir başlıq ola bilər):

| A (code) | B (name) | C (account_type) |
|----------|----------|------------------|
| 100 | Kassa | asset |
| … | … | liability / equity / revenue / expense |

- Kodlar **3-digit international** stil (plan qərarı).
- Başlıq sətirində `code` / `kod` / `hesab` → avtomatik skip.
- Fayl yolu (ops saxlayır, git-ə secret yox): _______________

---

## 3. Import addımları (staging)

1. Backup / snapshot staging DB.
2. Finance → CoA import (və ya xidmət `import_coa_from_xlsx`).
3. Yoxla: hesablar siyahısı; `code_for` rolları gəlir/AR üçün düzgün kodlara bağlanır.
4. Test charge → invoice confirm → JE; payment → JE.
5. Trial balance açılır; debet = kredit.

---

## 4. Mühasib UAT

Mühit: _______________ · Tarix: _______________ · Mühasib: _______________

| # | Meyar | Pass / Fail / Blocked | Qeyd |
|---|-------|----------------------|------|
| C1 | Real CoA Excel import uğurlu | | |
| C2 | Placeholder kodlar əvəz / deaktiv razılaşdırılıb | | |
| C3 | Charge→invoice→JE düzgün hesablar | | |
| C4 | Payment JE + paid status | | |
| C5 | TB daxili balanslı | | |
| C6 | TB ↔ xarici kitab (Excel/1C) tutuşdurma (əgər var) | | |
| C7 | **Statutory imza?** (adətən Xeyr — ERP daxili kitab) | ☐ İmza yox · ☐ İmza var: ____ | |

**§D nəticə:** C1–C5 Pass → functional checklist §D operator Pass ola bilər. C7 ayrıca hüquqi/mühasibat qərarıdır.

---

## 5. Bağlandıqdan sonra

1. [functional-readiness-checklist.md](functional-readiness-checklist.md) §D yeniləyin.
2. [../architecture/m10-billing-accounting.md](../architecture/m10-billing-accounting.md) «Defer: real CoA» qeydini bağlayın.
3. [../architecture/phase-gaps-and-open-questions.md](../architecture/phase-gaps-and-open-questions.md) P1 #7 / M10 yeniləyin.
