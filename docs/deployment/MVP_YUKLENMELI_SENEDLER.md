# İlkin MVP — yüklənməli sənədlər (ardıcıllıq)

Bu siyahı **fayl tələb edən** addımlardır. Kod/polish (nav gizlətmə, portal boş-state, sənəd download düyməsi və s.) ayrıdır və faylsız icra olunur.

Saxlama: əksər fayllar `var/private_media/` altına düşür (git-ə getmir). Yeni serverdə ya yenidən import/yükləmə, ya backup-dan bərpa.

---

## Ardıcıllıq (ehtiyac sırası ilə)

### Addım 0 — Deploy paketi (bir dəfə / yeniləmədə)

| # | Fayl | Harada | Qeyd |
|---|------|--------|------|
| 0.1 | `citypoint-app.zip` | Server `/opt/citypoint` | NetAdmin `CityPoint_NetAdmin_Yenileme_*.zip` |
| 0.2 | `OXU_MENI.txt` | Oxuyub əmrləri işlət | Secret yoxdur |
| 0.3 | Mövcud `bin/prod/.env` | Serverdə saxla | Zip-ə daxil **etmə**; toxunma |

Əmrlər: `migrate` → `compilemessages` → `collectstatic` → `systemctl restart citypoint`.

---

### Addım 1 — Ofis planları (Temiz CAD) — **mütləq**

Mənbə qovluq: `docs/City_Point_Ofisler_Temiz/`

| # | Fayl / tip | Nəticə |
|---|------------|--------|
| 1.1 | Bütün `*.dxf` | Sahə DXF (DWG tab) |
| 1.2 | Bütün `*.png` | Texniki plan preview |
| 1.3 | Bütün `*.json` | Paket meta |
| 1.4 | `space_drawing_map.csv` | `package_id → space_code` map |

**Əvvəl (F03 birləşmiş boş):** yoxdursa `CP-L061` yaradın — bax [`UPDATE_spaces_drawings.md`](UPDATE_spaces_drawings.md).

**Import:**

```bash
cd /opt/citypoint
python manage.py import_space_drawings \
  --root docs/City_Point_Ofisler_Temiz \
  --map docs/City_Point_Ofisler_Temiz/space_drawing_map.csv \
  --purge-mapped-spaces --replace
```

**Nəticə yolu:** `var/private_media/space_drawings/...`

**Əl ilə alternativ:** ERP → Sahə → Texniki plan / DWG yüklə (eyni storage).

---

### Addım 2 — Pilot şirkət sənədləri (portal “Sənədlər”) — **mütləq**

Hər pilot rezident şirkət üçün **ən azı 1–2 PDF**.

| # | Tövsiyə olunan sənəd | Format | Harada yüklə | Şərt |
|---|----------------------|--------|--------------|------|
| 2.1 | İcarə müqaviləsi (və ya qısa nümunə PDF) | PDF | ERP → Rezidentlər → [şirkət] → Sənədlər | `Portala görünən` = bəli |
| 2.2 | Daxili qaydalar / digər hüquqi | PDF | Eyni | `Portala görünən` = bəli |
| 2.3 | (İstəyə bağlı) Etibarnamə, bank arayışı, reyestr | PDF | Eyni | Tip seed artıq var |

**Saxlama:** `var/private_media/documents/...`  
**Yoxlama:** Portal → Sənədlər → **Yüklə** işləyir.

İstinad: [`UPDATE_resident_docs.md`](UPDATE_resident_docs.md).

---

### Addım 3 — Daxili prosedurlar — **mütləq**

| # | Sənəd | Format | Harada | Şərt |
|---|-------|--------|--------|------|
| 3.1 | Yanğın / evakuasiya qaydaları | PDF | ERP → Daxili prosedurlar → Yeni | Nəşr + **fayl mütləq** |
| 3.2 | (Tövsiyə) Qəbul / qonaq qaydaları | PDF | Eyni | Nəşr + fayl |

Faylsız prosedur portalda görünməz.

---

### Addım 4 — Elanlar — **mətn mütləq; fayl opsional**

| # | Nə | Format | Harada |
|---|----|--------|--------|
| 4.1 | Elan başlıq + mətn | — | Django Admin → Announcements (və ya Outlook sync) |
| 4.2 | (Opsional) əlavə | PDF / şəkil | Announcement attachment |

Minimum: **1 elan** (yalnız mətn kifayətdir — əlavə fayl tələb olunmur).

---

### Addım 5 — Security mərtəbə planları — **tövsiyə**

| # | Fayl | Format | Harada |
|---|------|--------|--------|
| 5.1 | 1–2 mərtəbə planı | DXF (və ya sistemin qəbul etdiyi) | Security → Planlar → upload |

Demo gücləndirir; portal/qəbul əsas axını üçün mütləq deyil.

---

### Addım 6 — Kart sifarişi üçün əməkdaş ID (opsional)

| # | Fayl | Format | Harada |
|---|------|--------|--------|
| 6.1 | Şəxsiyyət vəsiqəsi nüsxəsi | PDF/şəkil | Portal əməkdaş əlavə / kart sifarişi axını |

Kart sifarişi ticketi **faylsız da** göndərilə bilər; ID faylı prosesi tamamlayır.

---

### Addım 7 — Backup (fayl yükləmə deyil, bərpa üçün)

| # | Nə | Qeyd |
|---|----|------|
| 7.1 | PostgreSQL dump | DB |
| 7.2 | `var/private_media/` arxiv | Plan + PDF-lər |

---

## Qısa “minimum paket” (MVP yaşıl üçün)

1. Temiz import (Addım 1)  
2. Hər pilot şirkətə 1–2 PDF, portala görünən (Addım 2)  
3. ≥1 published prosedur PDF (Addım 3)  
4. ≥1 elan mətni (Addım 4 — faylsız olar)  
5. (Tövsiyə) 1 security mərtəbə planı (Addım 5)

## İlkin MVP üçün **yükləməyin**

- Anbar SKU şəkilləri  
- CRM təklif PDF-ləri  
- Billing / muhasibat export-lar  
- Website / marketinq asset-ləri  

---

## Kim nə edir

| Rol | Addımlar |
|-----|----------|
| NetAdmin / SysAdmin | 0, 1, 7 |
| Property / Admin | 2, 3, 4 |
| Security | 5 |
| Rezident (portal) | 6 (opsional) |
