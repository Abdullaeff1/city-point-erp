# Seed / import data

Bu qovluq və `var/` altındakı **təhlükəsizliksiz** iş faylları gitdədir.

## Sahələr (Building / Floor / Space)

```bash
docker compose -f bin/dev/docker-compose.yml exec web python manage.py loaddata docs/data/property_spaces.json

# Excel alternativ
docker compose -f bin/dev/docker-compose.yml exec web python manage.py import_lease_spaces --file docs/data/cp_icare_ve_bos_saheler.xlsx
```

`seed_demo` boş DB-də fixture-i avtomatik yükləyir (Space &lt; 20).

## Paylaşılmayan (təhlükəsizlik)

- `.env`
- `var/private_media/` (plan / private media)
- AxTrax JSON/log, «binada olanlar» export
- NetAdmin USB/update zip paketləri
