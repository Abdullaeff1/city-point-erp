# Yeniləmə: Rezident profili + Sənədlər (NetAdmin / SysAdmin)

Hüquqi/bank/əlaqə sahələri, arxiv, private sənəd storage və ERP/portal sənəd CRUD.

## 1. Kod + migrate

```bash
cd /opt/citypoint
python manage.py migrate
python manage.py migrate_document_files
python manage.py compilemessages
python manage.py collectstatic --noinput
sudo systemctl restart citypoint
```

Yeni miqrasiyalar:

- `residents.0014_resident_company_profile` (hüquqi/bank/arxiv + VÖEN backfill Party→company)
- `documents.0004_document_private_profile` (private storage, parent/lease, visible_to_resident, DocumentType seed)

## 2. Sənəd fayllarının köçürülməsi

`Document.file` artıq `PRIVATE_MEDIA_ROOT` altındadır (`var/private_media/`, default).

Köhnə ictimai `media/documents/...` fayllarını bir dəfə köçürün:

```bash
python manage.py migrate_document_files          # copy
python manage.py migrate_document_files --dry-run  # yoxlama
```

Köçürmədən sonra köhnə `media/documents/` silinə bilər (backup sonrası).

## 3. İctimai `/media/documents/` bağlanması

Django DEBUG media handler sənəd yollarını **403** qaytarır (`apps/core/media_views.py`).

Production nginx üçün nümunə:

```nginx
location ^~ /media/documents/ {
    return 403;
}
```

Endirmə yalnız:

- ERP: `/erp/residents/<slug>/documents/<id>/download/`
- Portal: `/portal/documents/<id>/download/` (yalnız `visible_to_resident` + şirkət scope)

## 4. UI qeydləri

- Sidebar **İcarələr** gizlədilib (Lease backend qalır; tarixlər rezident kartında).
- Rezidentlər → Ümumi | Sənədlər; create / edit / archive / unarchive.
- Unarchive portalı **avtomatik açmır** — `portal_active` ayrıca.
- Reception: yalnız ad, status, sahə/mərtəbə + qonaq; hüquqi/bank/sənəd yoxdur.

## 5. Yoxlama

- Admin ilə rezident kartında VÖEN / bank / sənəd yükləmə
- Başqa şirkətin sənəd ID-si → 404/403
- `/media/documents/...` → 403
- Arxiv şirkət portalda görünmür
- Yanlış məzmunlu `.pdf`/`.docx` rədd olunur
