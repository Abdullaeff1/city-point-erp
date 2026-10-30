# Yeniləmə: Sahələr + ofis planları (NetAdmin / SysAdmin)

Bu paketdə çoxşirkətli portal, sahə CRUD və DXF/texniki plan axını var.
Kod açıldıqdan sonra **mütləq** aşağıdakıları işlədin ki, server lokal ilə eyni işləsin.

## 1. Kod + migrate

```bash
cd /opt/citypoint
# zip açılıb, venv aktivdir fərz edilir
python manage.py migrate
python manage.py compilemessages
python manage.py collectstatic --noinput
sudo systemctl restart citypoint   # və ya gunicorn/nginx unit adınız
```

Yeni miqrasiyalar:

- `accounts.0005_portalcompanymembership` + `0006_backfill_portal_memberships`
- `property.0007_space_drawings`

## 2. Ofis planlarını DB-yə yükləyin (bir dəfə / yeniləmədə)

Paketdə mənbə fayllar: `docs/City_Point_Ofisler_DXF_PNG/`  
Mapping: `docs/City_Point_Ofisler_DXF_PNG/space_drawing_map.csv`

```bash
cd /opt/citypoint
python manage.py import_space_drawings \
  --map docs/City_Point_Ofisler_DXF_PNG/space_drawing_map.csv \
  --replace
```

Gözlənilən nəticə (təxminən): ~46 ofis × (DXF + PNG) = ~92 `SpaceDrawing`.

Mapsız qalan paketlər (U01/U02, bəzi kiçik konturlar) skip olunur — normaldır.

Mapping-i yenidən qurmaq lazımdırsa (sahə kodları dəyişibsə):

```bash
python scripts/build_space_drawing_map.py
python manage.py import_space_drawings --map docs/City_Point_Ofisler_DXF_PNG/space_drawing_map.csv --replace
```

## 3. Yoxlama

- ERP → Əmlak: mərtəbə/sahə siyahısı, **Sahə əlavə et**, düzəliş/silmə
- ERP → sahə kartı → DWG / Texniki plan tabları (Admin, Rəhbərlik, Property/FM)
- Portal → sahə → DWG / Texniki plan → icazə sorğusu → təsdiq → yükləmə (72 saat)

## 4. Qeyd

- Plan faylları `media/` altında private storage-dadır (`media/` zip-ə daxil edilmir).
- Import əmri faylları DB + media-ya yazır; migrate təkcə cədvəl yaradır.
- `.env` secret-ləri zip-də yoxdur — serverdəki mövcud `.env`-i saxlayın.
