# Rəhbərlik — gecikən işçilər və davamiyyət hesabatı (2026-11-27)

## Status

Portalda istifadəyə hazır: gecikənlər kartı/siyahısı, həftə/ay hesabatı, Excel, WhatsApp lokal önizləmə.
Canlı WhatsApp göndərişi **yoxdur** (ayrıca City Point qərarı tələb olunur).

## Marşrutlar

| URL | Ad | Kim |
|-----|-----|-----|
| `/erp/internal-staff/access/` | Siyahı + «Bu gün gecikənlər» kartı (`?late=1`) | Admin, Rəhbərlik (`hr.view`) |
| `/erp/internal-staff/access/<pk>/` | İşçi detalı + həftə/ay davamiyyət cədvəli | eyni |
| `/erp/internal-staff/access/<pk>/attendance.xlsx` | Eyni hesabla Excel | + `residents.export_access` |
| `/erp/internal-staff/access/<pk>/whatsapp-preview/` | Həftəlik şəxsi mətn önizləmə | Admin, Rəhbərlik |
| `/erp/` Rəhbərlik hub | KPI + qısa yol «Bu gün gecikənlər» | MANAGEMENT |
| `/erp/hr/` | eyni KPI / keçid | Admin / HR |

Security / digər əməliyyat rolları bu marşrutlara avtomatik giriş **almır**.

## Mənbələr

- **İşçilər:** `ResidentCompany(slug=city-point)` — yalnız daxili City Point; rezident və qonaqlar xaric.
- **Hadisələr:** `AccessEvent` (AxTrax RO sinxron), `result` ∈ davamiyyət nəticələri, `Asia/Baku`.
- **Oxuyucular:** Tur/Ent/Giriş/Çıxış/Gate; şaft və daxili qapılar hesabdan kənar (`is_building_perimeter_reader` / `is_shaft_reader`).
- **İş qrafiki:** sistemdə növbə/istirahat cədvəli yoxdur → standart **09:00**. Ekranda qeyd olunur. Şöbə master-data yoxdur → siyahıda «—».

## Hesablama (vahid xidmət)

Modul: `apps/residents/attendance.py`

- Gecikmə = ilk etibarlı **IN** − 09:00; ≤0 → vaxtında; &lt;60 s → «&lt;1 dəq»; təkrar IN gecikməni dəyişmir.
- Binada olma = bağlanmış IN→OUT intervallarının cəmi (fasilə çıxılır); ilk–son sadə fərq **istifadə olunmur**.
- Bu gün açıq interval ≠ keçmiş gündə çatışmayan çıxış; 18:00/23:59 avtomatik doldurulmur.
- Eyni hesab: ekran, Excel, WhatsApp mətni.

### Nümunə

09:12 IN, 13:00 OUT, 14:00 IN, 18:05 OUT → binada **7 saat 53 dəq**, gecikmə **12 dəq**, 1 gecikilən gün. Nahardan 14:10 qayıdış gecikmə yaratmır.

## WhatsApp — tələb olunan qərarlar (canlı göndəriş üçün)

1. Rəsmi xidmət hesabı / API kanalı
2. Təsdiqlənmiş işçi telefon nömrələri
3. Göndəriş qaydası və cədvəl (məs. bazar ertəsi səhər, keçmiş həftə)
4. Dedup: `attendance.wa.week.<employee_id>.<week_monday>` — göndərilməmiş hesabat «göndərildi» işarələnmir

## Testlər

```bash
docker compose exec -T web python manage.py test apps.residents.tests.test_attendance_report --verbosity=2 --keepdb
```

Nəticə (2026-11-27): **9/9 OK**.
