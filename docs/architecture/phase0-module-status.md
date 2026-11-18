# Modul statusu — cari vəziyyət

**Yenilənib:** 2026-11-18  
**Qayda:** Bu sənəd yalnız status qeydidir. Mövcud funksiyalar silinmir və “tam məhsul” kimi marketinq olunmur.

## Production qəbul qapısı (CRM)

Cari branch-dəki CRM/Satış dəyişiklikləri (**migration `0004`/`0005`**, PDF, Excel import, V2 UI, Admin CRM-dən çıxarılması və s.) **qəbul edilənə qədər production-hazır hesab olunmur.**

| Şərt | Status |
|------|--------|
| Kod `main` / branch-də mövcud | Bəli (lokal commit ola bilər) |
| `origin` / production deploy | Yalnız **yazılı qəbul** + UAT (A bölməsi) Pass-dan sonra |
| Marketinq / istifadəçi təlimatı “CRM hazırdır” | **Xeyr** — qəbuldan əvvəl |
| Yazılı qəbul formu | [../uat/crm-written-acceptance.md](../uat/crm-written-acceptance.md) — `AWAITING_SIGNATURE` |

Qəbul checklist: [../uat/functional-readiness-checklist.md](../uat/functional-readiness-checklist.md) §A.  
Boşluqlar: [phase-gaps-and-open-questions.md](phase-gaps-and-open-questions.md).  
Qərar: [BUSINESS_DECISIONS.md](BUSINESS_DECISIONS.md) §A.10.

## Təsnifat

| Kod | Azərbaycan | Məna |
|-----|------------|------|
| **işlək** | REAL / MVP | Gündəlik əməliyyatda istifadə oluna bilər; UAT və ops asılılıqları qeyd olunub |
| **qismən** | THIN | Model + xidmət və/və ya UI var; proses tam bağlanmayıb və ya təsdiq/CoA çatışmır |
| **skelet** | SCAFFOLD | Əsasən model / siyahı / redirect; istehsal prosesi sayılmır |

## Modul cədvəli

| Modul | Status | Qısa əsas |
|-------|--------|-----------|
| accounts (auth / invite) | **işlək** | Login, invite, şifrə sıfırlama, `must_set_password`, testlər |
| portal (rezident) | **işlək** | Scope/sessiya; ticket, əməkdaş, qonaq, kart sifarişi |
| reception | **işlək** | ERP UI + API + xidmətlər + testlər |
| tickets / service desk | **işlək** | Taxonomy, routing, SLA, queue; portal/ERP/security UI |
| residents | **işlək** | Şirkət, əməkdaş, access event, kart sifarişi, export |
| security portal | **işlək** | Hadisə, şirkət, alert, ticket, plan/patrul UI + testlər |
| integrations / AxTrax oxu | **işlək** | People/event sync + poller; **yazma yoxdur** (vendor) |
| crm / satış | **qismən** (prod gate) | Kodda sales MVP var; **production qəbulu gözlənilir** — yuxarıdakı qapıya bax |
| finance portal | **işlək** | `/finance/` UI, export, testlər — **mühasibat tam məhsul deyil** |
| property / spaces | **qismən** | Building/Floor/Space UI, drawings; occupancy Lease activate ilə körpü |
| leases | **qismən** | Activate/terminate cascade + lifecycle poller; UAT/siyasət açıq |
| parties | **qismən** | Party/Person + dual-write; portal SoT hələ Resident* |
| maintenance / work order | **qismən** | WO xidmətləri + ERP siyahı; preventiv/material zənciri natamam |
| documents | **qismən** | Kataloq + endirmə; versiya/retention siyasəti zəif |
| comms | **qismən** | In-app, elan, NotificationDispatch; SMTP ops asılı |
| rbac | **qismən** | Cədvəl/seed; hər yerdə enforce olunmur |
| workflows / approval | **qismən** | Offer/finance approval bağlı; ümumi mühərrik məhdud |
| billing | **qismən** | Charge/invoice/payment; journal xətası gizlənmir; real CoA yoxdur |
| accounting | **qismən** | Journal, trial balance, dövr; placeholder CoA |
| warehouse | **qismən** | Stock/hərəkət xidmətləri + ERP UI; inventar UAT yoxdur |
| procurement | **qismən** | PR→PO→receive xidmətləri + ERP UI; RFQ müqayisəsi zəif |
| api (public / reception) | **qismən** | JSON endpoint-lər; public lead/space stub |
| reporting / BI (ERP KPI) | **qismən** | ERP reports hub + CRM dual reports; BI məhsulu deyil |
| management_portal | **skelet** | `/management/` əsasən ERP redirect; ayrı portal məhsulu deyil |
| access_control (ayrı app) | **skelet** | Ayrı app yoxdur; məntiq residents + integrations-də |

## Qəbul qeydləri

- **işlək** = ops MVP, tam ERP və ya statutory mühasibat demək deyil.
- AxTrax kart “verildi” ERP statusu ≠ AxTrax-a yazılma.
- Billing/accounting **işlək finance shell** ilə birlikdə hələ **qismən** maliyyə nüvəsidir (CoA/VAT mühasib təsdiqi lazımdır).
- TLS / NetAdmin / production hardening ayrıca backlog-dadır; bu cədvəli dəyişmir.

## Əlaqəli sənədlər

- Boşluqlar (cari): [phase-gaps-and-open-questions.md](phase-gaps-and-open-questions.md)
- Boşluqlar (phase0): [phase0-business-gaps.md](phase0-business-gaps.md)
- UAT checklist: [../uat/functional-readiness-checklist.md](../uat/functional-readiness-checklist.md)
- CRM yazılı qəbul: [../uat/crm-written-acceptance.md](../uat/crm-written-acceptance.md)
- CoA UAT: [../uat/coa-import-uat.md](../uat/coa-import-uat.md)
- P0 ops cavabları: [../ops/p0-go-live-answers.md](../ops/p0-go-live-answers.md)
- NetAdmin 9: [../deployment/netadmin-handoff-checklist.md](../deployment/netadmin-handoff-checklist.md)
- Mərhələ qəbul meyarları + sübut: [../uat/phase-acceptance-criteria.md](../uat/phase-acceptance-criteria.md)
- Occupancy SoT: [party-space-lease-model.md](party-space-lease-model.md)
