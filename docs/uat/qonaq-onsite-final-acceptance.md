# On-site QONAQ / kart qəbulu — NetAdmin + Security

**Status:** hazırlıq COMPLETE · **canlı nəticələr:** AÇIQ (operator doldurur)  
**Əlaqə:** [`workflow-a-qonaq-live-acceptance.md`](workflow-a-qonaq-live-acceptance.md)  
**Qayda:** Yerli test Pass ≠ canlı imza. AxTrax **write** yoxdur — kart emit əl ilə.

---

## A. NetAdmin — konfiqurasiya

| # | Əməl | Gözlənilən | Sübut | Nəticə | İmza |
|---|------|------------|-------|--------|------|
| A1 | Test **qonaq kartı** AxTrax-da **QONAQ** qrupunda | Üzvlük təsdiqli | Ekran / qrup adı | | |
| A2 | **Nəzarət kartı** (QONAQ-da deyil) eyni oxuyucuda | ERP qonaq çıxışı yaratmamalı | Negativ sübut | | |
| A3 | OUT oxuyucu + istiqamət (`bReaderOut` / IdReader) | OUT kimi konfiq | Oxuyucu adı + Id | | |
| A4 | Poller / `axtrax_sync_status` | Yaşıl / son sync | CLI və ya dashboard | | |

---

## B. Reception + Security — qonaq axını

| # | Əməl | Gözlənilən | Sübut | Nəticə | İmza |
|---|------|------------|-------|--------|------|
| B1 | Test qonağı qəbul; kart nömrəsi **çap ilə eyni** | Ziyarət İçəridə; credential uyğun | Visit kodu | | |
| B2 | OUT oxuyucu → AxTrax vaxtı vs ERP `check_out_at` | Vaxtlar uyğun (poll delay ayrıca) | AxTrax + ERP vaxt | | |
| B3 | Eyni fiziki kart → ikinci ziyarət | A çıxışı dəyişmir; B ayrı interval | İki visit id | | |
| B4 | Delayed / replayed OUT (əgər mümkün) | Dublikat notify yox | SyncLog / UI | | |

---

## C. Əməkdaş kartı — əl ilə emit + RO sync

| # | Operator | Əməl | Gözlənilən | Sübut | Nəticə | İmza |
|---|----------|------|------------|-------|--------|------|
| C1 | Rezident | Portal kart sifarişi (istənilən səviyyə) | Ticket + `requested_access_level` | Ticket kodu | | |
| C2 | Security | Review / status irəliləyiş | `card_order_status` izlənir | Ticket / employee | | |
| C3 | NetAdmin | AxTrax-da fiziki kart emit (xaricdə) | Kart nömrəsi AxTrax-da | AxTrax id | | |
| C4 | System | RO people/events sync | ERP-də kart + **AxTrax** səviyyə; istənilən ayrıca | Employee sətiri | | |
| C5 | Security | Deaktiv sonrası attendance | Tarixçə qalır | Access view | | |

**Qeyd:** Portalda **İstənilən** ≠ **AxTrax** sütunları. Faktiki səviyyə yalnız sync-dən.

---

## D. Finance / digər (bu vərəqdən kənar)

Rəsmi faktura PDF layout / e-invoice — Finance qərarı (bax final portal hesabatı).
