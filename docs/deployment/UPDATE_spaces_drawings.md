# Yeniləmə: Sahələr + Temiz ofis planları (NetAdmin / SysAdmin)

Bu paketdə təmizlənmiş ofis CAD paketi (`docs/City_Point_Ofisler_Temiz/`) və
`import_space_drawings` əmri var. Kod açıldıqdan sonra **mütləq** aşağıdakıları
işlədin ki, server lokal ilə eyni sahə/plan vəziyyətində olsun.

## 1. Kod + migrate

```bash
cd /opt/citypoint
# zip açılıb, venv aktivdir fərz edilir
python manage.py migrate
python manage.py compilemessages
python manage.py collectstatic --noinput
sudo systemctl restart citypoint   # və ya gunicorn/nginx unit adınız
```

## 2. F03 birləşmiş boş sahə (CP-L061)

Temiz-də F03 Ofis 05+06 bir sahə kimi qəbul olunur. Lokalda `CP-L061` (107.7 m², Boş)
yaradılıb. Serverdə yoxdursa bir dəfə yaradın:

```bash
cd /opt/citypoint
python manage.py shell <<'PY'
from decimal import Decimal
from apps.property.models import Floor, Space, Occupancy, CommercialStatus, OperationalStatus
f03 = Floor.objects.get(code="F03")
space, created = Space.objects.get_or_create(
    code="CP-L061",
    defaults={
        "name": "Boş",
        "floor": f03,
        "area_m2": Decimal("107.7"),
        "rentable_area_m2": Decimal("107.70"),
        "occupancy": Occupancy.VACANT,
        "commercial_status": CommercialStatus.VACANT,
        "operational_status": OperationalStatus.AVAILABLE,
    },
)
print("created" if created else "exists", space.code, space.area_m2)
PY
```

## 3. Ofis planlarını DB-yə yükləyin (köhnələri silib yenilə)

Mənbə: `docs/City_Point_Ofisler_Temiz/`  
Mapping: `docs/City_Point_Ofisler_Temiz/space_drawing_map.csv`

```bash
cd /opt/citypoint
python manage.py import_space_drawings \
  --root docs/City_Point_Ofisler_Temiz \
  --map docs/City_Point_Ofisler_Temiz/space_drawing_map.csv \
  --purge-mapped-spaces \
  --replace
```

Gözlənilən nəticə (təxminən):

- ~52 paket × (DXF + PNG) → mapped sahələrdə ~106 `SpaceDrawing`
- U01 → F11 `CP-L056`, U02 → F13 `CP-L058` + `CP-L059`
- F12 → `CP-L057` (Bakı Fond Birjası)
- F09 Ofis 02 → Baker Tilly `CP-L051` (Ofis 03 ilə birlikdə)
- F03 Ofis 05+06 → `CP-L061`

`--purge-mapped-spaces` yalnız CSV-dəki sahələrdəki köhnə rəsmləri silir, sonra
Temiz fayllarını yenidən yazır.

## 4. Yoxlama

- ERP → Əmlak: F03-də `CP-L061` Boş görünür
- F11 / F12 / F13 sahələrində DXF + PNG var
- Baker Tilly (`CP-L051`): F09_Ofis_02 + F09_Ofis_03
- Digər mapped ofislərdə Temiz PNG/DXF

## 5. Qeyd

- Plan faylları `var/private_media/` altındadır (zip-ə daxil edilmir).
- Import əmri faylları DB + private media-ya yazır.
- `.env` secret-ləri zip-də yoxdur — serverdəki mövcud `.env`-i saxlayın.
- Köhnə `docs/City_Point_Ofisler_DXF_PNG/` mənbə olaraq qala bilər; aktiv import
  yolu Temiz qovluğudur.
