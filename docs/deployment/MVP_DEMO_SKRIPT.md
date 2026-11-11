# İlkin MVP — demo skripti (8 case)

Müddət: ~20–30 dəq. THIN modullar (CRM / Anbar / Billing / Muhasibat) sidebar-da gizlədilib — göstərməyin.

Fayl yükləmələri: [`MVP_YUKLENMELI_SENEDLER.md`](MVP_YUKLENMELI_SENEDLER.md).

---

## Case 1 — Pilot qonaq günü (faylsız)

1. Staff → Qəbul  
2. Qonaq girişi (şirkət / host / səbəb)  
3. Status içəridə → çıxış  
4. (Opsional) export  

**DoD:** jurnalda giriş + çıxış görünür.

---

## Case 2 — Portal müraciət (faylsız)

1. Rezident portal → Yeni müraciət  
2. Kateqoriya seç (Security və ya Service Desk)  
3. Staff siyahısında görünür → bağla  

**DoD:** ticket doğru şöbədə; portalda status yenilənir.

---

## Case 3 — Security axını (faylsız; poller lazımdır)

1. Security → ticket-lər  
2. Giriş/çıxış jurnalı (tarix filtri)  
3. Binada olanlar  

**DoD:** poller yaşıl; jurnal boş deyil (LAN AxTrax RO).

---

## Case 4 — Sahə planı (fayl: Temiz və ya əl ilə)

1. Staff: Temiz import və ya ERP-də DXF/PNG yüklə  
2. Portal → Sahə → Texniki plan / DWG → icazə sorğusu  
3. Staff təsdiq → portal **Yüklə**  

**DoD:** icazəli müddətli download.

---

## Case 5 — Kart sifarişi (faylsız kifayət)

1. Portal → Əməkdaşlar → kart sifarişi  
2. ERP/Security-də ticket  
3. Portalda badge: «Kart sifarişi gözləyir» / «Kart: Göndərilib»  

**DoD:** ticket + aydın status.

---

## Case 6 — Elan (faylsız olar)

1. Admin → Announcement (başlıq + mətn)  
2. Portalda görünür  

**DoD:** rezident oxuyur.

---

## Case 7 — Sənəd endirmə (fayl: PDF)

1. ERP → Rezident sənədi, `Portala görünən`  
2. Portal → Sənədlər → **Yüklə**  
3. (Əlavə) Sahə sənədlər tabında da **Yüklə**  

**DoD:** PDF endirilir.

---

## Case 8 — Çoxşirkət (əgər pilot çoxdursa; faylsız)

1. Portal şirkət seçimi  
2. Ticket / qonaq / əməkdaş scope yalnız seçilmiş şirkət  

**DoD:** digər şirkət məlumatı sızmır.

---

## Tez yoxlama (faylsız polish)

- [ ] ERP sidebar-da CRM / Anbar / Billing yoxdur  
- [ ] Portal sahədə «Texniki xidmət» tabı yoxdur  
- [ ] Qonaq boş-state: «Son N gündə…» (bu gün deyil)  
- [ ] Kart sifarişi badge aydındır  
